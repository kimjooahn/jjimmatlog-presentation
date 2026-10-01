"""Recalculate review-level content scores from cached rule-based text analyses."""
from __future__ import annotations

import argparse
import statistics
from pathlib import Path

from scoring.ai_review_pipeline import CACHE_PATH, RESULTS_CSV_PATH, read_cache, write_cache, write_results_csv
from scoring.content_scoring import calculate_review_content_result


def recalculate(cache: dict, cache_path: Path, csv_path: Path) -> list[dict]:
    entries = list(cache.values())
    for entry in entries:
        if entry.get("status") != "success" or not entry.get("text_analysis"):
            continue
        result = calculate_review_content_result(
            {
                "id": entry["review_id"],
                "reviewer_id": entry.get("reviewer_id"),
                "reviewer_name": entry.get("reviewer_name"),
                "restaurant_id": entry.get("restaurant_id"),
                "rating": entry["original_rating"],
                "review_text": entry["review_text"],
            },
            entry["text_analysis"],
        )
        for key in ("base_score", "evidence_coverage", "content_adjustment", "review_adjusted_score"):
            entry[key] = result[key]
    write_cache(cache_path, cache, "korean-rules-v1", provider="rule_based")
    write_results_csv(csv_path, entries)
    return entries


def print_five_star_summary(entries: list[dict]) -> None:
    five_star = [
        entry for entry in entries
        if entry.get("status") == "success" and int(entry["original_rating"]) == 5
    ]
    if not five_star:
        print("성공적으로 분석된 5점 리뷰가 없습니다.")
        return
    scores = [entry["review_adjusted_score"] for entry in five_star]
    print(
        f"5점 리뷰 {len(five_star)}개: 평균 {statistics.mean(scores):.6f}, "
        f"최소 {min(scores):.6f}, 최대 {max(scores):.6f}, "
        f"표준편차 {statistics.pstdev(scores):.6f}"
    )
    for heading, selected in (
        ("5점 보정점수 최저 5개", sorted(five_star, key=lambda item: item["review_adjusted_score"])[:5]),
        ("5점 보정점수 최고 5개", sorted(five_star, key=lambda item: item["review_adjusted_score"], reverse=True)[:5]),
    ):
        print(f"\n{heading}")
        for entry in selected:
            print(
                f"{entry['reviewer_id']} | {entry['reviewer_name']} | "
                f"content_adjustment={entry['content_adjustment']['total_adjustment']:+.6f} | "
                f"review_adjusted_score={entry['review_adjusted_score']:.6f} | {entry['review_text']}"
            )


def main() -> int:
    parser = argparse.ArgumentParser(description="기존 규칙 분석 결과의 리뷰 보정점수만 재계산")
    parser.add_argument("--cache", type=Path, default=CACHE_PATH)
    parser.add_argument("--csv-output", type=Path, default=RESULTS_CSV_PATH)
    args = parser.parse_args()
    cache = read_cache(args.cache, expected_provider="rule_based")
    if not cache:
        print("규칙 기반 분석 캐시가 없습니다. 먼저 python3 -m scoring.rule_based_pipeline 을 실행하세요.")
        return 2
    entries = recalculate(cache, args.cache, args.csv_output)
    successes = sum(entry.get("status") == "success" for entry in entries)
    print(f"재계산 리뷰 수: {successes}")
    print_five_star_summary(entries)
    print(f"\n분석 JSON: {args.cache}\n리뷰 점수 CSV: {args.csv_output}")
    print("reviewer-weights.csv와 restaurant-scores.csv는 수정하지 않았습니다.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())