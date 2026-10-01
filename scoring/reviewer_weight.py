"""Compute configurable reviewer weights from the five requested factors only."""
from __future__ import annotations

import statistics
from collections import defaultdict
from typing import Any

REVIEWER_COMPONENT_WEIGHTS = {
    "content_specificity": 0.30,
    "photo_score": 0.20,
    "rating_diversity_score": 0.25,
    "multi_restaurant_score": 0.15,
    "review_count_score": 0.10,
}
MIN_REVIEWER_WEIGHT = 0.30
MAX_REVIEWER_WEIGHT = 1.00
AVERAGE_LENGTH_FOR_FULL_SCORE = 100.0
CONTENT_LENGTH_SHARE = 0.50
CONTENT_ASPECT_COVERAGE_SHARE = 0.50
MAX_RATING_STANDARD_DEVIATION = 2.0
RESTAURANT_COUNT_FOR_FULL_SCORE = 4
REVIEW_COUNT_SATURATION = 5.0


def _clamp(value: float, lower: float = 0.0, upper: float = 1.0) -> float:
    return max(lower, min(upper, value))


def compute_reviewer_weights(
    reviews: list[dict[str, Any]],
    analysis_entries: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, float]]:
    analyses_by_review_id = {
        entry["review_id"]: entry
        for entry in analysis_entries
        if entry.get("status") == "success" and entry.get("review_id")
    }
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for review in reviews:
        reviewer_id = review.get("reviewer_id")
        if reviewer_id not in (None, ""):
            grouped[str(reviewer_id)].append(review)

    rows = []
    weights_by_reviewer_id = {}
    for reviewer_id, reviewer_reviews in grouped.items():
        ratings = [float(review["original_rating"]) for review in reviewer_reviews]
        lengths = [len(str(review.get("review_text", "")).strip()) for review in reviewer_reviews]
        photo_rate = sum(bool(review.get("has_photo")) for review in reviewer_reviews) / len(reviewer_reviews)
        restaurant_count = len({review.get("restaurant_id") for review in reviewer_reviews if review.get("restaurant_id")})
        rating_std = statistics.pstdev(ratings) if len(ratings) > 1 else 0.0

        specificity_samples = []
        for review in reviewer_reviews:
            analysis = analyses_by_review_id.get(review.get("review_id"))
            coverage = (analysis or {}).get("evidence_coverage")
            if not coverage or not coverage.get("total_aspect_count"):
                continue
            length_score = _clamp(
                len(str(review.get("review_text", "")).strip()) / AVERAGE_LENGTH_FOR_FULL_SCORE
            )
            aspect_score = _clamp(
                coverage["mentioned_aspect_count"] / coverage["total_aspect_count"]
            )
            specificity_samples.append(
                CONTENT_LENGTH_SHARE * length_score + CONTENT_ASPECT_COVERAGE_SHARE * aspect_score
            )
        content_specificity = statistics.mean(specificity_samples) if specificity_samples else 0.0
        rating_diversity_score = _clamp(rating_std / MAX_RATING_STANDARD_DEVIATION)
        multi_restaurant_score = _clamp(
            (restaurant_count - 1) / (RESTAURANT_COUNT_FOR_FULL_SCORE - 1)
        )
        review_count = len(reviewer_reviews)
        review_count_score = review_count / (review_count + REVIEW_COUNT_SATURATION)
        component_values = {
            "content_specificity": content_specificity,
            "photo_score": photo_rate,
            "rating_diversity_score": rating_diversity_score,
            "multi_restaurant_score": multi_restaurant_score,
            "review_count_score": review_count_score,
        }
        raw_weight = sum(
            component_values[name] * component_weight
            for name, component_weight in REVIEWER_COMPONENT_WEIGHTS.items()
        )
        reviewer_weight = _clamp(raw_weight, MIN_REVIEWER_WEIGHT, MAX_REVIEWER_WEIGHT)
        row = {
            "reviewer_id": reviewer_id,
            "reviewer_name": next(
                (review.get("reviewer_name") for review in reviewer_reviews if review.get("reviewer_name")),
                "",
            ),
            "review_count": review_count,
            "restaurant_count": restaurant_count,
            "average_review_length": round(statistics.mean(lengths), 2),
            "photo_rate": round(photo_rate, 4),
            "rating_mean": round(statistics.mean(ratings), 4),
            "rating_std": round(rating_std, 4),
            "analyzed_review_count": len(specificity_samples),
            **{name: round(value, 4) for name, value in component_values.items()},
            "raw_reviewer_weight": round(raw_weight, 6),
            "reviewer_weight": round(reviewer_weight, 6),
        }
        rows.append(row)
        weights_by_reviewer_id[reviewer_id] = reviewer_weight

    rows.sort(key=lambda row: row["reviewer_id"])
    return rows, weights_by_reviewer_id
