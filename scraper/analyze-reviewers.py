"""Create reviewer-level descriptive statistics from collected review JSON files."""
from __future__ import annotations

import argparse
import csv
import json
import statistics
from collections import Counter, defaultdict
from pathlib import Path

DATA_DIRECTORY = Path(__file__).resolve().parents[1] / "data"
DEFAULT_JSON_OUTPUT = DATA_DIRECTORY / "reviewer-analysis.json"
DEFAULT_CSV_OUTPUT = DATA_DIRECTORY / "reviewer-analysis.csv"
RATINGS = (1, 2, 3, 4, 5)
CSV_FIELDS = (
    "reviewer_id",
    "reviewer_name",
    "review_count",
    "restaurant_count",
    "photo_count",
    "photo_rate",
    "average_review_length",
    "average_rating",
    "rating_std",
    "rating_distribution",
    "one_star_count",
    "two_star_count",
    "three_star_count",
    "four_star_count",
    "five_star_count",
    "five_star_rate",
    "four_or_five_star_rate",
)


def round_rate(value: float) -> float:
    return round(value, 4)


def load_reviews(data_directory: Path) -> list[dict]:
    reviews = []
    for path in sorted(data_directory.glob("*-reviews.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        restaurant = payload.get("restaurant", {})
        restaurant_id = str(restaurant.get("kakaoPlaceId") or "")
        restaurant_name = restaurant.get("name", "")
        for review in payload.get("reviews", []):
            rating = float(review["rating"])
            if rating not in RATINGS:
                raise ValueError(f"평점은 1~5 정수여야 합니다: {path.name} ({rating})")
            reviewer_id = review.get("reviewer_id")
            reviews.append(
                {
                    "reviewer_id": str(reviewer_id) if reviewer_id not in (None, "") else None,
                    "reviewer_name": str(review.get("reviewer_name") or review.get("author") or ""),
                    "restaurant_id": str(review.get("restaurant_id") or restaurant_id),
                    "restaurant_name": restaurant_name,
                    "rating": int(rating),
                    "review_text": str(review.get("review_text") or review.get("text") or "").strip(),
                    "has_photo": bool(review.get("has_photo", review.get("hasImage", False))),
                }
            )
    return reviews


def analyze_reviewer(reviewer_id: str, reviews: list[dict]) -> dict:
    ratings = [review["rating"] for review in reviews]
    review_count = len(reviews)
    photo_count = sum(review["has_photo"] for review in reviews)
    lengths = [len(review["review_text"]) for review in reviews]
    counts = Counter(ratings)
    distribution = {str(rating): counts[rating] for rating in RATINGS}
    four_or_five_count = counts[4] + counts[5]
    return {
        "reviewer_id": reviewer_id,
        "reviewer_name": next((review["reviewer_name"] for review in reviews if review["reviewer_name"]), ""),
        "review_count": review_count,
        "restaurant_count": len({review["restaurant_id"] for review in reviews if review["restaurant_id"]}),
        "photo_count": photo_count,
        "photo_rate": round_rate(photo_count / review_count),
        "average_review_length": round(statistics.mean(lengths), 2),
        "average_rating": round(statistics.mean(ratings), 2),
        "rating_std": round(statistics.pstdev(ratings), 2),
        "rating_distribution": distribution,
        "one_star_count": counts[1],
        "two_star_count": counts[2],
        "three_star_count": counts[3],
        "four_star_count": counts[4],
        "five_star_count": counts[5],
        "five_star_rate": round_rate(counts[5] / review_count),
        "four_or_five_star_rate": round_rate(four_or_five_count / review_count),
    }


def build_report(reviews: list[dict]) -> dict:
    grouped: dict[str, list[dict]] = defaultdict(list)
    for review in reviews:
        if review["reviewer_id"] is not None:
            grouped[review["reviewer_id"]].append(review)

    reviewer_stats = [analyze_reviewer(reviewer_id, items) for reviewer_id, items in grouped.items()]
    reviewer_stats.sort(key=lambda item: item["reviewer_id"])
    all_ratings = [review["rating"] for review in reviews]
    rating_counts = Counter(all_ratings)
    photo_count = sum(review["has_photo"] for review in reviews)
    identified_review_count = sum(review["reviewer_id"] is not None for review in reviews)
    top_five_star_reviewers = sorted(
        reviewer_stats,
        key=lambda item: (-item["five_star_rate"], -item["review_count"], item["reviewer_id"]),
    )[:10]

    overall = {
        "review_count": len(reviews),
        "reviewer_count": len(reviewer_stats),
        "reviews_without_reviewer_id": len(reviews) - identified_review_count,
        "average_rating": round(statistics.mean(all_ratings), 2) if all_ratings else 0,
        "rating_distribution": {
            str(rating): {
                "count": rating_counts[rating],
                "rate": round_rate(rating_counts[rating] / len(reviews)) if reviews else 0,
            }
            for rating in RATINGS
        },
        "average_review_length": round(
            statistics.mean(len(review["review_text"]) for review in reviews), 2
        ) if reviews else 0,
        "photo_count": photo_count,
        "photo_rate": round_rate(photo_count / len(reviews)) if reviews else 0,
        "average_reviews_per_reviewer": round(len(reviews) / len(reviewer_stats), 2) if reviewer_stats else 0,
        "top_five_star_reviewers": top_five_star_reviewers,
    }
    return {
        "definitions": {
            "grouping_key": "reviewer_id",
            "reviewer_name_usage": "display_only",
            "average_review_length": "Unicode character count after trimming outer whitespace",
            "rating_std": "population standard deviation",
            "rates": "fraction from 0 to 1",
            "top_five_star_reviewers": "top 10 sorted by five_star_rate, then review_count",
            "scores": "descriptive statistics only; no reliability or adjusted score is calculated",
        },
        "overall": overall,
        "reviewers": reviewer_stats,
    }


def write_csv(path: Path, reviewers: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as output_file:
        writer = csv.DictWriter(output_file, fieldnames=CSV_FIELDS)
        writer.writeheader()
        for reviewer in reviewers:
            row = {key: reviewer[key] for key in CSV_FIELDS if key != "rating_distribution"}
            row["rating_distribution"] = json.dumps(reviewer["rating_distribution"], ensure_ascii=False)
            writer.writerow(row)


def print_summary(report: dict) -> None:
    overall = report["overall"]
    print("전체 리뷰 요약")
    print(f"전체 리뷰 평균 별점: {overall['average_rating']:.2f}")
    print("별점 비율: " + ", ".join(
        f"{rating}점 {item['rate']:.1%} ({item['count']}개)"
        for rating, item in overall["rating_distribution"].items()
    ))
    print(f"전체 리뷰 평균 글자 수: {overall['average_review_length']:.2f}")
    print(f"사진 첨부율: {overall['photo_rate']:.1%} ({overall['photo_count']}/{overall['review_count']})")
    print(f"리뷰어별 평균 리뷰 개수: {overall['average_reviews_per_reviewer']:.2f}")
    print(f"리뷰어 수: {overall['reviewer_count']}, reviewer_id 없는 리뷰: {overall['reviews_without_reviewer_id']}")

    print("\n리뷰어별 통계: reviewer_id | 이름 | 리뷰 수 | 사진 첨부율 | 평균 글자 수 | 평균 별점 | 별점 분포(1~5) | 5점 비율")
    for item in report["reviewers"]:
        counts = item["rating_distribution"]
        distribution = "/".join(str(counts[str(rating)]) for rating in RATINGS)
        print(
            f"{item['reviewer_id']} | {item['reviewer_name']} | {item['review_count']} | "
            f"{item['photo_rate']:.1%} | {item['average_review_length']:.2f} | "
            f"{item['average_rating']:.2f} | {distribution} | {item['five_star_rate']:.1%}"
        )

    print("\n5점 비율 상위 리뷰어 (상위 10명)")
    for item in overall["top_five_star_reviewers"]:
        print(
            f"{item['reviewer_id']} | {item['reviewer_name']} | "
            f"5점 비율 {item['five_star_rate']:.1%} | 리뷰 {item['review_count']}개"
        )


def main() -> None:
    parser = argparse.ArgumentParser(description="수집된 리뷰의 리뷰어별 기술 통계 생성")
    parser.add_argument("--data-dir", type=Path, default=DATA_DIRECTORY)
    parser.add_argument("--json-output", type=Path, default=DEFAULT_JSON_OUTPUT)
    parser.add_argument("--csv-output", type=Path, default=DEFAULT_CSV_OUTPUT)
    args = parser.parse_args()

    reviews = load_reviews(args.data_dir)
    report = build_report(reviews)
    args.json_output.parent.mkdir(parents=True, exist_ok=True)
    args.json_output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    write_csv(args.csv_output, report["reviewers"])
    print_summary(report)
    print(f"\nJSON 결과: {args.json_output}")
    print(f"CSV 결과: {args.csv_output}")


if __name__ == "__main__":
    main()