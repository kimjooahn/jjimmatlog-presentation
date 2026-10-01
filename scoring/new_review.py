"""Score one new review against the existing local review history, without saving it."""
from __future__ import annotations

from pathlib import Path
from typing import Any
from uuid import uuid4

from scoring.ai_review_pipeline import CACHE_PATH, DATA_DIRECTORY, load_source_reviews, read_cache
from scoring.content_scoring import calculate_review_content_result, validate_text_analysis
from scoring.restaurant_aggregation import build_restaurant_scores
from scoring.reviewer_weight import compute_reviewer_weights
from scoring.rule_based_review_analyzer import RuleBasedReviewAnalyzer


def score_new_review(
    review: dict[str, Any],
    data_directory: Path = DATA_DIRECTORY,
    cache_path: Path = CACHE_PATH,
) -> dict[str, Any]:
    """Calculate a review score, updated reviewer weight, and restaurant score in memory."""
    required_fields = {
        "reviewer_id", "reviewer_name", "restaurant_id", "rating", "review_text", "has_photo"
    }
    missing_fields = required_fields - review.keys()
    if missing_fields:
        raise ValueError(f"Missing review fields: {', '.join(sorted(missing_fields))}")
    if not isinstance(review["review_text"], str):
        raise ValueError("review_text must be a string")
    if not isinstance(review["has_photo"], bool):
        raise ValueError("has_photo must be a boolean")
    for field in ("reviewer_id", "reviewer_name", "restaurant_id"):
        if review[field] is None or not str(review[field]).strip():
            raise ValueError(f"{field} must not be empty")

    existing_reviews = load_source_reviews(data_directory)
    cache = read_cache(cache_path, expected_provider="rule_based")
    missing_analysis = [
        item["review_id"]
        for item in existing_reviews
        if cache.get(item["review_id"], {}).get("status") != "success"
    ]
    if missing_analysis:
        raise ValueError(
            f"Successful rule-based analyses are missing for {len(missing_analysis)} existing reviews"
        )
    existing_entries = [cache[item["review_id"]] for item in existing_reviews]

    reviewer_id = str(review["reviewer_id"])
    restaurant_id = str(review["restaurant_id"])
    review_id = f"presentation-{uuid4().hex}"
    restaurant_name = next(
        (item["restaurant_name"] for item in existing_reviews if item["restaurant_id"] == restaurant_id),
        "",
    )
    source_review = {
        "review_id": review_id,
        "reviewer_id": reviewer_id,
        "reviewer_name": str(review["reviewer_name"]),
        "restaurant_id": restaurant_id,
        "restaurant_name": restaurant_name,
        "original_rating": review["rating"],
        "review_text": review["review_text"],
        "has_photo": review["has_photo"],
    }

    text_analysis = RuleBasedReviewAnalyzer().analyze(source_review["review_text"])
    validate_text_analysis(text_analysis, source_review["review_text"])
    calculated = calculate_review_content_result(
        {
            "id": review_id,
            "reviewer_id": reviewer_id,
            "reviewer_name": source_review["reviewer_name"],
            "restaurant_id": restaurant_id,
            "rating": source_review["original_rating"],
            "review_text": source_review["review_text"],
        },
        text_analysis,
    )
    new_entry = {
        **source_review,
        "status": "success",
        "text_analysis": text_analysis,
        "evidence_coverage": calculated["evidence_coverage"],
        "base_score": calculated["base_score"],
        "content_adjustment": calculated["content_adjustment"],
        "review_adjusted_score": calculated["review_adjusted_score"],
    }

    reviewer_rows, weights_by_reviewer_id = compute_reviewer_weights(
        [*existing_reviews, source_review], [*existing_entries, new_entry]
    )
    reviewer_row = next(row for row in reviewer_rows if row["reviewer_id"] == reviewer_id)
    restaurant_rows, _ = build_restaurant_scores(
        [*existing_reviews, source_review],
        [*existing_entries, new_entry],
        weights_by_reviewer_id,
    )
    restaurant_row = next(row for row in restaurant_rows if row["restaurant_id"] == restaurant_id)

    return {
        "review": new_entry,
        "reviewer": reviewer_row,
        "restaurant": restaurant_row,
    }