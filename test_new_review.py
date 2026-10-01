from __future__ import annotations

import math
import unittest
from unittest.mock import patch

from scoring.content_scoring import calculate_evidence_coverage
from scoring.new_review import score_new_review
from scoring.rule_based_review_analyzer import RuleBasedReviewAnalyzer


class NewReviewTests(unittest.TestCase):
    def test_new_review_runs_existing_scoring_weight_and_aggregation(self) -> None:
        existing_review = {
            "review_id": "existing-review",
            "reviewer_id": "reviewer-1",
            "reviewer_name": "발표 테스트 사용자",
            "restaurant_id": "restaurant-1",
            "restaurant_name": "테스트 식당",
            "original_rating": 4,
            "review_text": "맛있어요",
            "has_photo": True,
        }
        old_analysis = RuleBasedReviewAnalyzer().analyze(existing_review["review_text"])
        existing_entry = {
            **existing_review,
            "status": "success",
            "text_analysis": old_analysis,
            "evidence_coverage": calculate_evidence_coverage(old_analysis),
            "base_score": 3.4,
            "content_adjustment": {"total_adjustment": 0.066667},
            "review_adjusted_score": 3.466667,
        }
        with (
            patch("scoring.new_review.load_source_reviews", return_value=[existing_review]),
            patch(
                "scoring.new_review.read_cache",
                return_value={"existing-review": existing_entry},
            ),
        ):
            result = score_new_review({
                "reviewer_id": "reviewer-1",
                "reviewer_name": "발표 테스트 사용자",
                "restaurant_id": "restaurant-1",
                "rating": 5,
                "review_text": "만두가 정말 맛있고 양도 많아요. 그런데 주차가 너무 힘들었어요.",
                "has_photo": False,
            })

        scored_review = result["review"]
        self.assertEqual(scored_review["base_score"], 3.7)
        self.assertEqual(len(scored_review["text_analysis"]["criteria"]), 10)
        self.assertEqual(
            scored_review["text_analysis"]["criteria"]["parking_access"]["sentiment"],
            "negative",
        )
        self.assertGreater(scored_review["review_adjusted_score"], 3.7)
        self.assertEqual(result["reviewer"]["review_count"], 2)
        self.assertGreaterEqual(result["reviewer"]["reviewer_weight"], 0.30)
        self.assertLessEqual(result["reviewer"]["reviewer_weight"], 1.00)
        self.assertEqual(result["restaurant"]["review_count"], 2)
        self.assertTrue(math.isclose(
            result["restaurant"]["weighted_score"],
            (3.466667 + scored_review["review_adjusted_score"]) / 2,
            rel_tol=0.0,
            abs_tol=1e-6,
        ))
        self.assertTrue(scored_review["review_id"].startswith("presentation-"))


if __name__ == "__main__":
    unittest.main(verbosity=2)