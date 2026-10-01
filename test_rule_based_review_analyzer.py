from __future__ import annotations

import unittest

from scoring.content_scoring import ASPECTS, validate_text_analysis
from scoring.rule_based_review_analyzer import analyze_review_text


class RuleBasedReviewAnalyzerTests(unittest.TestCase):
    def test_example_separates_taste_portion_and_parking(self) -> None:
        text = "만두가 정말 맛있고 양도 많아요. 그런데 주차가 너무 힘들었어요."
        analysis = analyze_review_text(text)
        criteria = analysis["criteria"]
        self.assertEqual(criteria["taste"], {
            "sentiment": "positive", "intensity": 3, "evidence": "정말 맛있고"
        })
        self.assertEqual(criteria["portion"]["sentiment"], "positive")
        self.assertEqual(criteria["portion"]["intensity"], 2)
        self.assertEqual(criteria["parking_access"]["sentiment"], "negative")
        self.assertEqual(criteria["parking_access"]["intensity"], 3)
        self.assertTrue(criteria["parking_access"]["evidence"] in text)

    def test_negated_polarity_is_flipped(self) -> None:
        taste_text = "맛있지 않아요"
        parking_text = "주차가 어렵지 않았어요"
        taste = analyze_review_text(taste_text)["criteria"]["taste"]
        parking = analyze_review_text(parking_text)["criteria"]["parking_access"]
        self.assertEqual((taste["sentiment"], taste["intensity"]), ("negative", 2))
        self.assertEqual((parking["sentiment"], parking["intensity"]), ("positive", 2))
        self.assertIn(taste["evidence"], taste_text)
        self.assertIn(parking["evidence"], parking_text)

    def test_unmentioned_aspects_are_never_inferred(self) -> None:
        text = "맛있어요"
        criteria = analyze_review_text(text)["criteria"]
        self.assertEqual(criteria["taste"]["sentiment"], "positive")
        for aspect in set(ASPECTS) - {"taste"}:
            self.assertEqual(criteria[aspect], {
                "sentiment": "not_mentioned", "intensity": 0, "evidence": None
            })

    def test_explicit_neutral_mentions_are_not_marked_unmentioned(self) -> None:
        criteria = analyze_review_text("가격은 적당하고 양은 보통이에요")["criteria"]
        self.assertEqual(criteria["price"]["sentiment"], "neutral")
        self.assertEqual(criteria["portion"]["sentiment"], "neutral")
        self.assertEqual(criteria["price"]["intensity"], 1)

    def test_all_results_match_shared_schema_and_keep_evidence_verbatim(self) -> None:
        text = "맛은 괜찮지만 가격이 비쌌습니다. 직원은 친절했어요."
        analysis = analyze_review_text(text)
        validate_text_analysis(analysis, text)
        self.assertEqual(set(analysis["criteria"]), set(ASPECTS))


if __name__ == "__main__":
    unittest.main(verbosity=2)