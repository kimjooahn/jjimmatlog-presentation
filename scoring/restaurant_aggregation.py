"""Aggregate successful review scores by restaurant with reviewer weights."""
from __future__ import annotations

import csv
from collections import defaultdict
from pathlib import Path
from typing import Any

from scoring.reviewer_weight import MIN_REVIEWER_WEIGHT

REVIEWER_WEIGHT_CSV_FIELDS = (
    "reviewer_id",
    "reviewer_name",
    "review_count",
    "restaurant_count",
    "average_review_length",
    "photo_rate",
    "rating_mean",
    "rating_std",
    "rating_diversity_score",
    "content_specificity",
    "photo_score",
    "multi_restaurant_score",
    "review_count_score",
    "reviewer_weight",
)
RESTAURANT_SCORE_CSV_FIELDS = (
    "restaurant_id",
    "restaurant_name",
    "review_count",
    "weighted_score",
    "average_reviewer_weight",
)


def build_restaurant_scores(
    reviews: list[dict[str, Any]],
    analysis_entries: list[dict[str, Any]],
    weights_by_reviewer_id: dict[str, float],
) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]]]:
    source_by_id = {review["review_id"]: review for review in reviews}
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for entry in analysis_entries:
        if entry.get("status") != "success" or entry.get("review_adjusted_score") is None:
            continue
        restaurant_id = str(entry.get("restaurant_id") or "")
        if restaurant_id:
            grouped[restaurant_id].append(entry)

    rows = []
    details = {}
    for restaurant_id, entries in grouped.items():
        contributions = []
        weighted_sum = 0.0
        weight_sum = 0.0
        reviewer_weights = []
        for entry in entries:
            reviewer_id = entry.get("reviewer_id")
            weight = weights_by_reviewer_id.get(str(reviewer_id), MIN_REVIEWER_WEIGHT)
            score = float(entry["review_adjusted_score"])
            contribution = score * weight
            weighted_sum += contribution
            weight_sum += weight
            reviewer_weights.append(weight)
            contributions.append({
                "review_id": entry.get("review_id"),
                "reviewer_id": reviewer_id,
                "reviewer_name": entry.get("reviewer_name"),
                "original_rating": entry.get("original_rating"),
                "review_adjusted_score": score,
                "reviewer_weight": weight,
                "weighted_contribution": contribution,
                "review_text": entry.get("review_text", ""),
            })
        restaurant_name = next(
            (source_by_id.get(entry.get("review_id"), {}).get("restaurant_name") for entry in entries
             if source_by_id.get(entry.get("review_id"), {}).get("restaurant_name")),
            "",
        )
        row = {
            "restaurant_id": restaurant_id,
            "restaurant_name": restaurant_name,
            "review_count": len(entries),
            "weighted_score": round(weighted_sum / weight_sum, 6) if weight_sum else None,
            "average_reviewer_weight": round(sum(reviewer_weights) / len(reviewer_weights), 6),
        }
        rows.append(row)
        details[restaurant_id] = {
            **row,
            "weighted_numerator": weighted_sum,
            "reviewer_weight_denominator": weight_sum,
            "contributions": contributions,
        }
    rows.sort(key=lambda row: row["restaurant_id"])
    return rows, details


def write_reviewer_weights_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as output_file:
        writer = csv.DictWriter(output_file, fieldnames=REVIEWER_WEIGHT_CSV_FIELDS)
        writer.writeheader()
        writer.writerows({field: row.get(field) for field in REVIEWER_WEIGHT_CSV_FIELDS} for row in rows)


def write_restaurant_scores_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as output_file:
        writer = csv.DictWriter(output_file, fieldnames=RESTAURANT_SCORE_CSV_FIELDS)
        writer.writeheader()
        writer.writerows({field: row.get(field) for field in RESTAURANT_SCORE_CSV_FIELDS} for row in rows)


def print_extreme_calculations(details: dict[str, dict[str, Any]]) -> None:
    if not details:
        print("식당별 계산 결과가 없습니다.")
        return
    lowest = min(details.values(), key=lambda row: row["weighted_score"])
    highest = max(details.values(), key=lambda row: row["weighted_score"])
    for label, restaurant in (("최고점 식당 계산 상세", highest), ("최저점 식당 계산 상세", lowest)):
        print(
            f"\n{label}: {restaurant['restaurant_name']} ({restaurant['restaurant_id']})\n"
            f"분자={restaurant['weighted_numerator']:.6f}, "
            f"분모={restaurant['reviewer_weight_denominator']:.6f}, "
            f"점수={restaurant['weighted_score']:.6f}"
        )
        for item in restaurant["contributions"]:
            print(
                f"  {item['reviewer_id']} | {item['review_adjusted_score']:.6f} * "
                f"{item['reviewer_weight']:.6f} = {item['weighted_contribution']:.6f} | "
                f"{item['review_text']}"
            )