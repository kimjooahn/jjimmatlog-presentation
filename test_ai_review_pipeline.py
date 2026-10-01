from __future__ import annotations

import asyncio
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from scoring.ai_review_pipeline import (
    OpenAIReviewAnalyzer,
    RESPONSE_SCHEMA,
    analyze_one,
    process_reviews,
    read_cache,
    select_test_reviews,
)
from scoring.restaurant_aggregation import build_restaurant_scores
from scoring.reviewer_weight import (
    MAX_REVIEWER_WEIGHT,
    MIN_REVIEWER_WEIGHT,
    compute_reviewer_weights,
)


def make_review(review_id: str, rating: int, text: str = "맛있어요") -> dict:
    return {
        "review_id": review_id,
        "reviewer_id": f"user-{review_id}",
        "reviewer_name": "테스트 사용자",
        "restaurant_id": "restaurant-1",
        "original_rating": rating,
        "review_text": text,
    }


def analysis_for(text: str) -> dict:
    criteria = {
        aspect: {"sentiment": "not_mentioned", "intensity": 0, "evidence": None}
        for aspect in RESPONSE_SCHEMA["properties"]["criteria"]["required"]
    }
    if "맛있어요" in text:
        criteria["taste"] = {"sentiment": "positive", "intensity": 1, "evidence": "맛있어요"}
    return {"criteria": criteria}


class FakeAnalyzer:
    model = "fake-test-model"

    def __init__(self):
        self.calls = []

    def analyze(self, review_text: str) -> dict:
        self.calls.append(review_text)
        if review_text == "API 실패":
            raise RuntimeError("simulated API failure")
        return analysis_for(review_text)


class AIReviewPipelineTests(unittest.TestCase):
    def test_selects_five_reviews_covering_each_rating(self) -> None:
        reviews = [make_review(f"id-{rating}", rating) for rating in (1, 2, 3, 4, 5)]
        selected = select_test_reviews(reviews)
        self.assertEqual(len(selected), 5)
        self.assertEqual({review["original_rating"] for review in selected}, {1, 2, 3, 4, 5})

    def test_analysis_is_validated_and_passed_to_existing_calculator(self) -> None:
        review = make_review("real-id", 5)
        result = analyze_one(review, FakeAnalyzer())
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["reviewer_id"], "user-real-id")
        self.assertEqual(result["original_rating"], 5)
        self.assertEqual(result["base_score"], 3.7)
        self.assertEqual(result["review_adjusted_score"], 3.733333)
        self.assertNotIn("reviewer_weight", result)

    def test_invalid_nonverbatim_evidence_is_rejected(self) -> None:
        class InvalidEvidenceAnalyzer:
            def analyze(self, review_text: str) -> dict:
                result = analysis_for(review_text)
                result["criteria"]["taste"]["evidence"] = "추측한 표현"
                return result

        with self.assertRaisesRegex(ValueError, "copied from the source review text"):
            analyze_one(make_review("evidence", 5), InvalidEvidenceAnalyzer())

    def test_api_error_is_cached_and_later_reviews_continue(self) -> None:
        reviews = [make_review("ok", 5), make_review("failed", 4, "API 실패"), make_review("after", 3)]
        analyzer = FakeAnalyzer()
        with tempfile.TemporaryDirectory() as temp_directory:
            cache_path = Path(temp_directory) / "cache.json"
            cache = {}
            asyncio.run(process_reviews(reviews, cache, analyzer, cache_path))
            self.assertEqual([cache[item["review_id"]]["status"] for item in reviews], ["success", "error", "success"])
            self.assertEqual(len(analyzer.calls), 3)
            self.assertTrue(cache_path.exists())
            saved = json.loads(cache_path.read_text(encoding="utf-8"))
            self.assertEqual(len(saved["reviews"]), 3)

    def test_openai_client_posts_structured_response_schema(self) -> None:
        response = MagicMock()
        response.__enter__.return_value.read.return_value = json.dumps(
            {"choices": [{"message": {"content": json.dumps(analysis_for("맛있어요"), ensure_ascii=False)}}]}
        ).encode("utf-8")
        with patch("scoring.ai_review_pipeline.urlopen", return_value=response) as mocked_urlopen:
            result = OpenAIReviewAnalyzer("test-key").analyze("맛있어요")
        self.assertEqual(result, analysis_for("맛있어요"))
        request = mocked_urlopen.call_args.args[0]
        request_data = json.loads(request.data.decode("utf-8"))
        self.assertEqual(request_data["response_format"]["json_schema"]["schema"], RESPONSE_SCHEMA)
        self.assertNotIn("rating", request_data["messages"][1]["content"])

    def test_rule_based_cache_is_not_reused_as_openai_analysis(self) -> None:
        with tempfile.TemporaryDirectory() as temp_directory:
            cache_path = Path(temp_directory) / "analysis.json"
            cache_path.write_text(json.dumps({
                "provider": "rule_based",
                "reviews": [{"review_id": "same-id", "status": "success"}],
            }), encoding="utf-8")
            self.assertEqual(read_cache(cache_path, expected_provider="openai"), {})
            self.assertIn("same-id", read_cache(cache_path, expected_provider="rule_based"))

    def test_reviewer_weight_uses_rating_diversity_and_is_bounded(self) -> None:
        reviews = [
            {**make_review("a1", 5), "has_photo": True},
            {**make_review("b1", 5), "reviewer_id": "same-ratings", "has_photo": True},
            {**make_review("c1", 5), "reviewer_id": "varied-ratings", "has_photo": True},
            {**make_review("d1", 1), "reviewer_id": "varied-ratings", "has_photo": True},
        ]
        analyses = []
        for review in reviews:
            analysis = analysis_for(review["review_text"])
            analysis["criteria"]["taste"] = {"sentiment": "positive", "intensity": 1, "evidence": "맛있어요"}
            analyses.append({
                **review,
                "status": "success",
                "evidence_coverage": {
                    "mentioned_aspect_count": 10,
                    "total_aspect_count": 10,
                },
            })
        rows, weights = compute_reviewer_weights(reviews, analyses)
        self.assertGreater(weights["varied-ratings"], weights["same-ratings"])
        self.assertGreaterEqual(weights["user-a1"], MIN_REVIEWER_WEIGHT)
        self.assertLess(weights["user-a1"], 0.5)
        self.assertTrue(all(MIN_REVIEWER_WEIGHT <= weight <= MAX_REVIEWER_WEIGHT for weight in weights.values()))
        self.assertEqual(len(rows), 3)
        sparse_review = {**make_review("sparse", 5), "reviewer_id": "sparse", "has_photo": False}
        _, sparse_weights = compute_reviewer_weights([sparse_review], [])
        self.assertEqual(sparse_weights["sparse"], MIN_REVIEWER_WEIGHT)

    def test_restaurant_score_is_reviewer_weighted_average(self) -> None:
        reviews = [make_review("one", 5), make_review("two", 1)]
        entries = [
            {**reviews[0], "status": "success", "review_adjusted_score": 4.0},
            {**reviews[1], "status": "success", "review_adjusted_score": 2.0},
        ]
        rows, details = build_restaurant_scores(reviews, entries, {"user-one": 0.75, "user-two": 0.5})
        self.assertAlmostEqual(rows[0]["weighted_score"], (4.0 * 0.75 + 2.0 * 0.5) / 1.25)
        self.assertAlmostEqual(details["restaurant-1"]["reviewer_weight_denominator"], 1.25)


if __name__ == "__main__":
    unittest.main(verbosity=2)