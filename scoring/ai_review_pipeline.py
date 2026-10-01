"""Analyze review text with OpenAI, cache by review ID, and calculate review-level scores."""
from __future__ import annotations

import argparse
import asyncio
import csv
import json
import os
import sys
import tempfile
from collections import defaultdict
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from dotenv import load_dotenv

from scoring.content_scoring import ASPECTS, calculate_review_content_result, validate_text_analysis
from scoring.restaurant_aggregation import (
    build_restaurant_scores,
    print_extreme_calculations,
    write_restaurant_scores_csv,
    write_reviewer_weights_csv,
)
from scoring.reviewer_weight import compute_reviewer_weights

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATA_DIRECTORY = PROJECT_ROOT / "data"
CACHE_PATH = DATA_DIRECTORY / "review-text-analysis.json"
RESULTS_CSV_PATH = DATA_DIRECTORY / "review-adjusted-results.csv"
REVIEWER_WEIGHTS_CSV_PATH = DATA_DIRECTORY / "reviewer-weights.csv"
RESTAURANT_SCORES_CSV_PATH = DATA_DIRECTORY / "restaurant-scores.csv"
OPENAI_CHAT_COMPLETIONS_URL = "https://api.openai.com/v1/chat/completions"
DEFAULT_MODEL = "gpt-4o-mini"
REQUEST_TIMEOUT_SECONDS = 60
CSV_FIELDS = (
    "review_id", "reviewer_id", "reviewer_name", "restaurant_id", "original_rating",
    "review_text", "base_score", "content_adjustment", "review_adjusted_score",
    "analysis_status", "analysis_error",
)

RESPONSE_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["criteria"],
    "properties": {
        "criteria": {
            "type": "object",
            "additionalProperties": False,
            "required": list(ASPECTS),
            "properties": {
                aspect: {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["sentiment", "intensity", "evidence"],
                    "properties": {
                        "sentiment": {"type": "string", "enum": ["positive", "neutral", "negative", "not_mentioned"]},
                        "intensity": {"type": "integer", "minimum": 0, "maximum": 3},
                        "evidence": {"type": ["string", "null"]},
                    },
                }
                for aspect in ASPECTS
            },
        }
    },
}

SYSTEM_PROMPT = """You extract explicit evaluation signals from Korean restaurant reviews.
Do not infer unstated information. For every aspect not explicitly discussed,
return sentiment=not_mentioned, intensity=0, evidence=null. For a mentioned
aspect, use sentiment positive, neutral, or negative and intensity 1 (weak),
2 (moderate), or 3 (strong). Evidence must be a short, verbatim contiguous
substring of the supplied review. Do not return ratings, scores, reviewer trust,
or restaurant-level judgments. Return only the requested JSON object."""


def load_source_reviews(data_directory: Path = DATA_DIRECTORY) -> list[dict[str, Any]]:
    reviews = []
    seen_ids = set()
    for path in sorted(data_directory.glob("*-reviews.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        restaurant = payload.get("restaurant", {})
        restaurant_id = str(restaurant.get("kakaoPlaceId") or "")
        for source in payload.get("reviews", []):
            review_id = str(source.get("id") or source.get("review_id") or "")
            if not review_id:
                raise ValueError(f"리뷰 ID가 없는 원본 항목입니다: {path.name}")
            if review_id in seen_ids:
                raise ValueError(f"중복 review_id가 있어 캐시 키가 모호합니다: {review_id}")
            seen_ids.add(review_id)
            reviews.append({
                "review_id": review_id,
                "reviewer_id": source.get("reviewer_id"),
                "reviewer_name": source.get("reviewer_name") or source.get("author"),
                "restaurant_id": str(source.get("restaurant_id") or restaurant_id),
                "restaurant_name": str(restaurant.get("name") or ""),
                "original_rating": source.get("rating"),
                "review_text": str(source.get("review_text") or source.get("text") or ""),
                "has_photo": bool(source.get("has_photo", source.get("hasImage", False))),
            })
    return reviews


def select_test_reviews(reviews: list[dict[str, Any]], limit: int = 5) -> list[dict[str, Any]]:
    """Select one review per available original rating, then fill in source order."""
    selected = []
    selected_ids = set()
    for rating in (1, 2, 3, 4, 5):
        match = next((item for item in reviews if float(item["original_rating"]) == rating), None)
        if match and match["review_id"] not in selected_ids:
            selected.append(match)
            selected_ids.add(match["review_id"])
        if len(selected) >= limit:
            return selected
    for review in reviews:
        if review["review_id"] not in selected_ids:
            selected.append(review)
            selected_ids.add(review["review_id"])
        if len(selected) >= limit:
            break
    return selected


def read_cache(cache_path: Path, expected_provider: str = "openai") -> dict[str, dict[str, Any]]:
    if not cache_path.exists():
        return {}
    payload = json.loads(cache_path.read_text(encoding="utf-8"))
    cache_provider = payload.get("provider", "openai")
    if cache_provider != expected_provider:
        print(
            f"{cache_provider} 분석 캐시는 {expected_provider} 실행에서 재사용하지 않습니다.",
            flush=True,
        )
        return {}
    return {str(entry["review_id"]): entry for entry in payload.get("reviews", []) if entry.get("review_id")}


def write_cache(
    cache_path: Path,
    cache: dict[str, dict[str, Any]],
    model: str,
    provider: str = "openai",
) -> None:
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"schema_version": "1.0", "provider": provider, "model": model, "reviews": list(cache.values())}
    temporary_path = None
    try:
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=cache_path.parent, delete=False) as temp_file:
            json.dump(payload, temp_file, ensure_ascii=False, indent=2)
            temp_file.write("\n")
            temporary_path = Path(temp_file.name)
        temporary_path.replace(cache_path)
    finally:
        if temporary_path and temporary_path.exists():
            temporary_path.unlink()


def error_entry(review: dict[str, Any], error: Exception) -> dict[str, Any]:
    return {
        **review, "status": "error", "text_analysis": None, "evidence_coverage": None,
        "base_score": None, "content_adjustment": None, "review_adjusted_score": None,
        "error": {"type": type(error).__name__, "message": str(error)[:1000]},
    }


class OpenAIReviewAnalyzer:
    def __init__(self, api_key: str, model: str = DEFAULT_MODEL):
        self.api_key = api_key
        self.model = model

    def analyze(self, review_text: str) -> dict[str, Any]:
        body = {
            "model": self.model,
            "temperature": 0,
            "response_format": {
                "type": "json_schema",
                "json_schema": {"name": "review_text_analysis", "strict": True, "schema": RESPONSE_SCHEMA},
            },
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": "Analyze only this review text. Quote evidence verbatim.\n\n" + review_text},
            ],
        }
        request = Request(
            OPENAI_CHAT_COMPLETIONS_URL,
            data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
            headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urlopen(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
                response_data = json.loads(response.read().decode("utf-8"))
        except HTTPError as error:
            detail = error.read().decode("utf-8", errors="replace")
            try:
                detail = json.loads(detail).get("error", {}).get("message", detail)
            except json.JSONDecodeError:
                pass
            raise RuntimeError(f"OpenAI HTTP {error.code}: {detail[:500]}") from error
        except URLError as error:
            raise RuntimeError(f"OpenAI network error: {error.reason}") from error
        try:
            analysis = json.loads(response_data["choices"][0]["message"]["content"])
        except (KeyError, IndexError, TypeError, json.JSONDecodeError) as error:
            raise RuntimeError("OpenAI response did not contain valid structured JSON") from error
        if not isinstance(analysis, dict):
            raise RuntimeError("AI analysis must be a JSON object")
        return analysis


def analyze_one(review: dict[str, Any], analyzer: OpenAIReviewAnalyzer) -> dict[str, Any]:
    text_analysis = analyzer.analyze(review["review_text"])
    validate_text_analysis(text_analysis, review["review_text"])
    calculated = calculate_review_content_result({
        "id": review["review_id"], "reviewer_id": review["reviewer_id"],
        "reviewer_name": review["reviewer_name"], "restaurant_id": review["restaurant_id"],
        "rating": review["original_rating"], "review_text": review["review_text"],
    }, text_analysis)
    return {
        **review, "status": "success", "text_analysis": text_analysis,
        "evidence_coverage": calculated["evidence_coverage"],
        "base_score": calculated["base_score"],
        "content_adjustment": calculated["content_adjustment"],
        "review_adjusted_score": calculated["review_adjusted_score"], "error": None,
    }


async def process_reviews(reviews, cache, analyzer, cache_path: Path, provider: str = "openai") -> None:
    for index, review in enumerate(reviews, 1):
        if cache.get(review["review_id"], {}).get("status") == "success":
            print(f"캐시 사용 {index}/{len(reviews)}: {review['review_id']}", flush=True)
            continue
        try:
            cache[review["review_id"]] = analyze_one(review, analyzer)
            print(f"분석 성공 {index}/{len(reviews)}: {review['review_id']}", flush=True)
        except Exception as error:
            cache[review["review_id"]] = error_entry(review, error)
            print(f"분석 실패 {index}/{len(reviews)}: {review['review_id']} ({error})", flush=True)
        write_cache(cache_path, cache, analyzer.model, provider)


def select_result_entries(reviews, cache):
    return [cache[review["review_id"]] for review in reviews if review["review_id"] in cache]


def write_results_csv(path: Path, entries: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as output_file:
        writer = csv.DictWriter(output_file, fieldnames=CSV_FIELDS)
        writer.writeheader()
        for entry in entries:
            adjustment = entry.get("content_adjustment")
            writer.writerow({
                "review_id": entry.get("review_id"), "reviewer_id": entry.get("reviewer_id"),
                "reviewer_name": entry.get("reviewer_name"), "restaurant_id": entry.get("restaurant_id"),
                "original_rating": entry.get("original_rating"), "review_text": entry.get("review_text"),
                "base_score": entry.get("base_score"),
                "content_adjustment": adjustment.get("total_adjustment") if adjustment else None,
                "review_adjusted_score": entry.get("review_adjusted_score"),
                "analysis_status": entry.get("status"),
                "analysis_error": entry.get("error", {}).get("message") if entry.get("error") else None,
            })


def print_test_results(entries: list[dict[str, Any]]) -> None:
    print("\n5개 리뷰 테스트 결과")
    for entry in entries:
        print(f"\nreview_id: {entry['review_id']}")
        print(f"AI 분석 성공 여부: {entry['status'] == 'success'}")
        if entry["status"] == "success":
            print(json.dumps(entry["text_analysis"], ensure_ascii=False, indent=2))
            print("evidence 원문 일치: True (구조 검증 완료)")
            print(f"review_adjusted_score: {entry['review_adjusted_score']:.6f}")
            print("API 오류: 없음")
        else:
            print(f"API/분석 오류: {entry['error']['type']}: {entry['error']['message']}")


def print_full_statistics(entries: list[dict[str, Any]]) -> None:
    successful = [entry for entry in entries if entry.get("status") == "success"]
    failed = [entry for entry in entries if entry.get("status") != "success"]
    grouped: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for entry in successful:
        grouped[int(entry["original_rating"])].append(entry)
    print(f"\n전체 분석 성공 리뷰 수: {len(successful)}")
    print(f"실패 리뷰 수: {len(failed)}")
    for rating in range(1, 6):
        scores = [entry["review_adjusted_score"] for entry in grouped[rating]]
        if scores:
            print(f"{rating}점 평균 보정점수: {sum(scores) / len(scores):.6f} ({len(scores)}개)")
    five_star = [entry["review_adjusted_score"] for entry in grouped[5]]
    if five_star:
        print(f"5점 평균/최소/최대: {sum(five_star) / len(five_star):.6f} / {min(five_star):.6f} / {max(five_star):.6f}")
    all_scores = [entry["review_adjusted_score"] for entry in successful]
    if all_scores:
        print(f"전체 평균 보정점수: {sum(all_scores) / len(all_scores):.6f}")
        for label, ordered in (
            ("가장 높은 10개 리뷰", sorted(successful, key=lambda entry: entry["review_adjusted_score"], reverse=True)[:10]),
            ("가장 낮은 10개 리뷰", sorted(successful, key=lambda entry: entry["review_adjusted_score"])[:10]),
        ):
            print(f"\n{label}")
            for entry in ordered:
                print(f"{entry['review_adjusted_score']:.6f} | {entry['original_rating']}점 | {entry['review_text']}")


def print_reviewer_and_restaurant_statistics(reviewer_rows, restaurant_rows, restaurant_details) -> None:
    weights = [row["reviewer_weight"] for row in reviewer_rows]
    print(f"\n전체 reviewer 수: {len(reviewer_rows)}")
    if weights:
        print(
            f"reviewer_weight 평균/최소/최대: {sum(weights) / len(weights):.6f} / "
            f"{min(weights):.6f} / {max(weights):.6f}"
        )
    print("\n식당별 최종 weighted_score")
    for row in restaurant_rows:
        print(
            f"{row['restaurant_id']} | {row['restaurant_name']} | "
            f"리뷰 {row['review_count']}개 | 점수 {row['weighted_score']:.6f} | "
            f"평균 reviewer_weight {row['average_reviewer_weight']:.6f}"
        )
    print_extreme_calculations(restaurant_details)


def main() -> int:
    parser = argparse.ArgumentParser(description="AI 리뷰 분석 및 리뷰별 보정점수 시뮬레이션")
    parser.add_argument("--test-only", action="store_true", help="5개 API 테스트까지만 실행하고 전체 분석은 멈춤")
    parser.add_argument("--data-dir", type=Path, default=DATA_DIRECTORY)
    parser.add_argument("--cache", type=Path, default=CACHE_PATH)
    parser.add_argument("--csv-output", type=Path, default=RESULTS_CSV_PATH)
    args = parser.parse_args()

    load_dotenv(PROJECT_ROOT / ".env")
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        print("OPENAI_API_KEY가 없습니다. .env.example을 .env로 복사해 키를 설정하세요. 키를 채팅에 붙여넣지 마세요.", file=sys.stderr)
        return 2
    reviews = load_source_reviews(args.data_dir)
    if not reviews:
        print("분석할 리뷰가 없습니다.", file=sys.stderr)
        return 2
    model = os.getenv("OPENAI_MODEL", DEFAULT_MODEL)
    cache = read_cache(args.cache)
    analyzer = OpenAIReviewAnalyzer(api_key, model)
    test_reviews = select_test_reviews(reviews, 5)
    asyncio.run(process_reviews(test_reviews, cache, analyzer, args.cache))
    test_entries = select_result_entries(test_reviews, cache)
    print_test_results(test_entries)
    write_results_csv(args.csv_output, select_result_entries(reviews, cache))

    test_success = len(test_entries) == len(test_reviews) and all(item.get("status") == "success" for item in test_entries)
    if not test_success:
        print("5개 테스트가 전부 성공하지 않아 전체 리뷰 분석은 실행하지 않았습니다.")
        return 1
    if args.test_only:
        print("5개 테스트가 성공했습니다. --test-only 설정으로 전체 분석을 중단했습니다.")
        return 0
    remaining = [review for review in reviews if cache.get(review["review_id"], {}).get("status") != "success"]
    asyncio.run(process_reviews(remaining, cache, analyzer, args.cache))
    entries = select_result_entries(reviews, cache)
    write_results_csv(args.csv_output, entries)
    reviewer_rows, weights_by_reviewer_id = compute_reviewer_weights(reviews, entries)
    write_reviewer_weights_csv(REVIEWER_WEIGHTS_CSV_PATH, reviewer_rows)
    restaurant_rows, restaurant_details = build_restaurant_scores(reviews, entries, weights_by_reviewer_id)
    write_restaurant_scores_csv(RESTAURANT_SCORES_CSV_PATH, restaurant_rows)
    print_full_statistics(entries)
    print_reviewer_and_restaurant_statistics(reviewer_rows, restaurant_rows, restaurant_details)
    print(
        f"\n분석 캐시: {args.cache}\n리뷰별 결과 CSV: {args.csv_output}"
        f"\n리뷰어 가중치 CSV: {REVIEWER_WEIGHTS_CSV_PATH}"
        f"\n식당 점수 CSV: {RESTAURANT_SCORES_CSV_PATH}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())