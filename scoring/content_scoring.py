"""Experimental, review-level content scoring; no restaurant aggregation."""
from __future__ import annotations

import math
from typing import Any

ASPECTS = (
    "taste",
    "food_quality",
    "portion",
    "price",
    "service",
    "waiting",
    "parking_access",
    "facility_hygiene",
    "atmosphere",
    "revisit_intent",
)
SENTIMENTS = {"positive", "neutral", "negative", "not_mentioned"}

# Initial experiment values only; revisit after inspecting sample results.
BASE_SCORE_BY_ORIGINAL_RATING = {
    1: 1.2,
    2: 2.0,
    3: 2.8,
    4: 3.4,
    5: 3.7,
}

ASPECT_IMPORTANCE = {
    "taste": 0.25,
    "food_quality": 0.20,
    "portion": 0.08,
    "price": 0.12,
    "service": 0.08,
    "waiting": 0.06,
    "parking_access": 0.04,
    "facility_hygiene": 0.08,
    "atmosphere": 0.04,
    "revisit_intent": 0.05,
}

SENTIMENT_ADJUSTMENT = {
    "positive": {1: 0.05, 2: 0.10, 3: 0.15},
    "neutral": {1: 0.0, 2: 0.0, 3: 0.0},
    "negative": {1: -0.07, 2: -0.14, 3: -0.21},
    "not_mentioned": {0: 0.0},
}
CONTENT_ADJUSTMENT_SCALE = 8.0
COVERAGE_SATURATION_ASPECTS = 3
EVIDENCE_SPECIFICITY_REFERENCE_CHARS = 20.0


def validate_settings() -> None:
    if set(ASPECT_IMPORTANCE) != set(ASPECTS):
        raise ValueError("ASPECT_IMPORTANCE must define exactly the configured aspects")
    if not math.isclose(sum(ASPECT_IMPORTANCE.values()), 1.0, abs_tol=1e-9):
        raise ValueError("ASPECT_IMPORTANCE values must total 1.0")
    if set(BASE_SCORE_BY_ORIGINAL_RATING) != {1, 2, 3, 4, 5}:
        raise ValueError("A base score must be configured for each original rating")


def validate_text_analysis(text_analysis: dict[str, Any], review_text: str) -> None:
    criteria = text_analysis.get("criteria")
    if not isinstance(criteria, dict) or set(criteria) != set(ASPECTS):
        raise ValueError("text_analysis.criteria must contain exactly the ten configured aspects")

    for aspect in ASPECTS:
        result = criteria[aspect]
        sentiment = result.get("sentiment")
        intensity = result.get("intensity")
        evidence = result.get("evidence")
        if sentiment not in SENTIMENTS:
            raise ValueError(f"Invalid sentiment for {aspect}: {sentiment}")
        if not isinstance(intensity, int) or isinstance(intensity, bool) or not 0 <= intensity <= 3:
            raise ValueError(f"Intensity for {aspect} must be an integer from 0 to 3")
        if sentiment == "not_mentioned":
            if intensity != 0 or evidence is not None:
                raise ValueError(f"Unmentioned aspect {aspect} must use intensity 0 and null evidence")
        elif intensity == 0 or not isinstance(evidence, str) or not evidence.strip():
            raise ValueError(f"Mentioned aspect {aspect} needs intensity 1-3 and explicit evidence")
        elif evidence not in review_text:
            raise ValueError(f"Evidence for {aspect} must be copied from the source review text")


def calculate_evidence_coverage(text_analysis: dict[str, Any]) -> dict[str, Any]:
    """Measure explicit aspect coverage and the specificity of cited evidence."""
    criteria = text_analysis["criteria"]
    mentioned = [aspect for aspect in ASPECTS if criteria[aspect]["sentiment"] != "not_mentioned"]
    evidence_lengths = {
        aspect: len(criteria[aspect]["evidence"].strip()) if aspect in mentioned else 0
        for aspect in ASPECTS
    }
    evidence_specificity = (
        sum(min(length / EVIDENCE_SPECIFICITY_REFERENCE_CHARS, 1.0) for length in evidence_lengths.values())
        / len(mentioned)
        if mentioned
        else 0.0
    )
    coverage_factor = min(len(mentioned) / COVERAGE_SATURATION_ASPECTS, 1.0)
    evidence_specificity_factor = 0.5 + 0.5 * evidence_specificity if mentioned else 0.0
    return {
        "mentioned_aspect_count": len(mentioned),
        "total_aspect_count": len(ASPECTS),
        "mentioned_aspects": mentioned,
        "not_mentioned_aspects": [aspect for aspect in ASPECTS if aspect not in mentioned],
        "evidence_character_count_by_aspect": evidence_lengths,
        "average_evidence_specificity": round(evidence_specificity, 6),
        "coverage_factor": round(coverage_factor, 6),
        "evidence_specificity_factor": round(evidence_specificity_factor, 6),
        "coverage_score": round(coverage_factor * evidence_specificity_factor, 6),
        "formula_status": "initial_experiment",
    }


def calculate_content_adjustment(text_analysis: dict[str, Any]) -> dict[str, Any]:
    """Scale weighted sentiment by the number of explicitly mentioned aspects."""
    per_aspect = {}
    unscaled_weighted_adjustment = 0.0
    for aspect in ASPECTS:
        result = text_analysis["criteria"][aspect]
        sentiment = result["sentiment"]
        intensity = result["intensity"]
        unweighted = SENTIMENT_ADJUSTMENT[sentiment][intensity]
        weighted = unweighted * ASPECT_IMPORTANCE[aspect]
        unscaled_weighted_adjustment += weighted
        per_aspect[aspect] = {
            "importance": ASPECT_IMPORTANCE[aspect],
            "unweighted_adjustment": unweighted,
            "weighted_adjustment": round(weighted, 6),
        }
    coverage = calculate_evidence_coverage(text_analysis)
    content_factor = coverage["coverage_factor"]
    total_adjustment = unscaled_weighted_adjustment * CONTENT_ADJUSTMENT_SCALE * content_factor
    for aspect in ASPECTS:
        per_aspect[aspect]["scaled_adjustment"] = round(
            per_aspect[aspect]["weighted_adjustment"] * CONTENT_ADJUSTMENT_SCALE * content_factor,
            6,
        )
    return {
        "method": "weighted_sentiment_x_aspect_coverage",
        "unscaled_weighted_adjustment": round(unscaled_weighted_adjustment, 6),
        "content_adjustment_scale": CONTENT_ADJUSTMENT_SCALE,
        "coverage_factor": coverage["coverage_factor"],
        "evidence_specificity_factor": coverage["evidence_specificity_factor"],
        "content_factor": content_factor,
        "per_aspect": per_aspect,
        "total_adjustment": round(total_adjustment, 6),
    }


def calculate_review_content_result(
    review: dict[str, Any], text_analysis: dict[str, Any]
) -> dict[str, Any]:
    """Build one review's content-adjusted result without reviewer weighting or aggregation."""
    validate_settings()
    original_rating_value = float(review["rating"])
    if not original_rating_value.is_integer() or int(original_rating_value) not in BASE_SCORE_BY_ORIGINAL_RATING:
        raise ValueError("original_rating must be an integer from 1 to 5")
    original_rating = int(original_rating_value)
    review_text = str(review.get("review_text", review.get("text", "")))
    validate_text_analysis(text_analysis, review_text)

    base_score = BASE_SCORE_BY_ORIGINAL_RATING[original_rating]
    content_adjustment = calculate_content_adjustment(text_analysis)
    return {
        "review_id": review.get("review_id", review.get("id")),
        "reviewer_id": review.get("reviewer_id"),
        "reviewer_name": review.get("reviewer_name"),
        "restaurant_id": review.get("restaurant_id"),
        "original_rating": original_rating,
        "base_score": base_score,
        "text_analysis": text_analysis,
        "evidence_coverage": calculate_evidence_coverage(text_analysis),
        "content_adjustment": content_adjustment,
        "review_adjusted_score": round(base_score + content_adjustment["total_adjustment"], 6),
    }


validate_settings()