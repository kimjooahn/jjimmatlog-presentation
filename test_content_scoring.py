from __future__ import annotations

import unittest

from scoring.content_scoring import (
    ASPECTS,
    ASPECT_IMPORTANCE,
    BASE_SCORE_BY_ORIGINAL_RATING,
    calculate_review_content_result,
)


def make_case(review_id: str, rating: int, text: str, mentions: dict) -> tuple[dict, dict]:
    criteria = {
        aspect: {"sentiment": "not_mentioned", "intensity": 0, "evidence": None}
        for aspect in ASPECTS
    }
    for aspect, (sentiment, intensity, evidence) in mentions.items():
        criteria[aspect] = {"sentiment": sentiment, "intensity": intensity, "evidence": evidence}
    review = {
        "review_id": review_id,
        "reviewer_id": f"test-{review_id}",
        "reviewer_name": "가상 리뷰어",
        "restaurant_id": "virtual-restaurant",
        "rating": rating,
        "review_text": text,
    }
    return review, {"criteria": criteria}


TEST_CASES = [
    (
        "A: 5점, 여러 항목에 강한 긍정",
        *make_case(
            "virtual-a",
            5,
            "맛이 아주 좋고 재료도 신선합니다. 양도 넉넉하고 가격도 합리적입니다. "
            "직원이 매우 친절하고 기다림 없이 주차도 편했습니다. 매장은 깨끗하고 분위기도 좋습니다. 꼭 다시 오고 싶습니다.",
            {
                "taste": ("positive", 3, "맛이 아주 좋고"),
                "food_quality": ("positive", 3, "재료도 신선합니다"),
                "portion": ("positive", 2, "양도 넉넉하고"),
                "price": ("positive", 2, "가격도 합리적입니다"),
                "service": ("positive", 3, "직원이 매우 친절하고"),
                "waiting": ("positive", 2, "기다림 없이"),
                "parking_access": ("positive", 2, "주차도 편했습니다"),
                "facility_hygiene": ("positive", 2, "매장은 깨끗하고"),
                "atmosphere": ("positive", 2, "분위기도 좋습니다"),
                "revisit_intent": ("positive", 3, "꼭 다시 오고 싶습니다"),
            },
        ),
    ),
    (
        "B: 5점, 주차·대기 부정 포함",
        *make_case(
            "virtual-b",
            5,
            "맛도 좋고 재료가 신선해요. 가격도 괜찮았습니다. 다만 주차 공간이 좁고 오래 기다렸어요.",
            {
                "taste": ("positive", 2, "맛도 좋고"),
                "food_quality": ("positive", 2, "재료가 신선해요"),
                "price": ("positive", 1, "가격도 괜찮았습니다"),
                "waiting": ("negative", 2, "오래 기다렸어요"),
                "parking_access": ("negative", 2, "주차 공간이 좁고"),
            },
        ),
    ),
    (
        "C: 4점, 구체적인 장단점",
        *make_case(
            "virtual-c",
            4,
            "만두피가 얇고 속이 꽉 차 맛있었어요. 양은 보통이고 가격은 비쌌습니다. "
            "직원 응대가 아쉬웠고 20분 기다렸어요. 분위기는 좋지만 다시 올지는 고민됩니다.",
            {
                "taste": ("positive", 2, "맛있었어요"),
                "food_quality": ("positive", 3, "만두피가 얇고 속이 꽉 차"),
                "portion": ("neutral", 1, "양은 보통이고"),
                "price": ("negative", 2, "가격은 비쌌습니다"),
                "service": ("negative", 2, "직원 응대가 아쉬웠고"),
                "waiting": ("negative", 2, "20분 기다렸어요"),
                "atmosphere": ("positive", 1, "분위기는 좋지만"),
                "revisit_intent": ("neutral", 2, "다시 올지는 고민됩니다"),
            },
        ),
    ),
    (
        "D: 5점, 짧은 긍정 리뷰",
        *make_case("virtual-d", 5, "맛있어요", {"taste": ("positive", 1, "맛있어요")}),
    ),
]


def calculate_cases() -> list[tuple[str, dict]]:
    return [
        (name, calculate_review_content_result(review, analysis))
        for name, review, analysis in TEST_CASES
    ]


class ContentScoringTests(unittest.TestCase):
    def test_aspect_importance_totals_one(self) -> None:
        self.assertAlmostEqual(sum(ASPECT_IMPORTANCE.values()), 1.0)

    def test_four_virtual_cases_calculate(self) -> None:
        results = dict(calculate_cases())
        self.assertEqual(len(results), 4)
        for result in results.values():
            self.assertEqual(len(result["text_analysis"]["criteria"]), 10)
            self.assertAlmostEqual(
                result["base_score"], BASE_SCORE_BY_ORIGINAL_RATING[result["original_rating"]]
            )
        self.assertGreater(
            results["A: 5점, 여러 항목에 강한 긍정"]["content_adjustment"]["total_adjustment"],
            results["D: 5점, 짧은 긍정 리뷰"]["content_adjustment"]["total_adjustment"],
        )
        self.assertLess(
            results["B: 5점, 주차·대기 부정 포함"]["content_adjustment"]["total_adjustment"],
            results["A: 5점, 여러 항목에 강한 긍정"]["content_adjustment"]["total_adjustment"],
        )

    def test_unmentioned_aspects_are_zero_and_not_inferred(self) -> None:
        for _, result in calculate_cases():
            for aspect, criterion in result["text_analysis"]["criteria"].items():
                if criterion["sentiment"] == "not_mentioned":
                    self.assertEqual(criterion["intensity"], 0, aspect)
                    self.assertIsNone(criterion["evidence"], aspect)
                    self.assertEqual(
                        result["content_adjustment"]["per_aspect"][aspect]["unweighted_adjustment"], 0
                    )

    def test_result_separates_original_rating_and_excludes_later_stages(self) -> None:
        result = calculate_cases()[0][1]
        self.assertEqual(result["original_rating"], 5)
        self.assertEqual(result["reviewer_id"], "test-virtual-a")
        self.assertIn("evidence_coverage", result)
        self.assertGreater(result["evidence_coverage"]["coverage_score"], 0)
        self.assertLessEqual(result["evidence_coverage"]["coverage_score"], 1)
        self.assertNotIn("reviewer_weight", result)
        self.assertNotIn("restaurant_final_score", result)

    def test_same_five_star_rating_changes_with_coverage_and_evidence(self) -> None:
        sparse_text = "맛있어요"
        sparse = {"criteria": {aspect: {"sentiment": "not_mentioned", "intensity": 0, "evidence": None} for aspect in ASPECTS}}
        sparse["criteria"]["taste"] = {"sentiment": "positive", "intensity": 2, "evidence": "맛있어요"}
        detailed_text = "음식이 맛있고 양도 많아요. 직원도 친절했어요."
        detailed = {"criteria": {aspect: {"sentiment": "not_mentioned", "intensity": 0, "evidence": None} for aspect in ASPECTS}}
        detailed["criteria"].update({
            "taste": {"sentiment": "positive", "intensity": 3, "evidence": "맛있고"},
            "portion": {"sentiment": "positive", "intensity": 2, "evidence": "양도 많아요"},
            "service": {"sentiment": "positive", "intensity": 2, "evidence": "친절했어요"},
        })
        sparse_score = calculate_review_content_result({"id": "sparse", "rating": 5, "review_text": sparse_text}, sparse)
        detailed_score = calculate_review_content_result({"id": "detailed", "rating": 5, "review_text": detailed_text}, detailed)
        longer_evidence = {"criteria": {**sparse["criteria"]}}
        longer_evidence["criteria"]["taste"] = {
            "sentiment": "positive", "intensity": 2, "evidence": "정말 맛있어요"
        }
        longer_score = calculate_review_content_result(
            {"id": "longer", "rating": 5, "review_text": "정말 맛있어요"}, longer_evidence
        )
        self.assertEqual(sparse_score["base_score"], detailed_score["base_score"])
        self.assertEqual(
            sparse_score["content_adjustment"]["total_adjustment"],
            longer_score["content_adjustment"]["total_adjustment"],
        )
        self.assertGreater(detailed_score["review_adjusted_score"], sparse_score["review_adjusted_score"] + 0.1)
        self.assertAlmostEqual(sparse_score["review_adjusted_score"], 3.766667)

    def test_negative_evidence_offsets_positive_evidence(self) -> None:
        text = "음식이 정말 맛있어요. 가격이 너무 비싸고 주차가 너무 불편하고 오래 기다렸어요."
        criteria = {aspect: {"sentiment": "not_mentioned", "intensity": 0, "evidence": None} for aspect in ASPECTS}
        criteria.update({
            "taste": {"sentiment": "positive", "intensity": 3, "evidence": "정말 맛있어요"},
            "price": {"sentiment": "negative", "intensity": 2, "evidence": "너무 비싸고"},
            "parking_access": {"sentiment": "negative", "intensity": 3, "evidence": "너무 불편"},
            "waiting": {"sentiment": "negative", "intensity": 2, "evidence": "오래 기다렸어요"},
        })
        result = calculate_review_content_result({"id": "mixed", "rating": 5, "review_text": text}, {"criteria": criteria})
        positive_only = {"criteria": {aspect: {"sentiment": "not_mentioned", "intensity": 0, "evidence": None} for aspect in ASPECTS}}
        positive_only["criteria"]["taste"] = criteria["taste"]
        positive_result = calculate_review_content_result({"id": "positive", "rating": 5, "review_text": text}, positive_only)
        self.assertLess(result["review_adjusted_score"], positive_result["review_adjusted_score"])


if __name__ == "__main__":
    test_result = unittest.TextTestRunner(verbosity=2).run(
        unittest.defaultTestLoader.loadTestsFromTestCase(ContentScoringTests)
    )
    print("\n가상 리뷰 계산 결과")
    for name, result in calculate_cases():
        print(
            f"{name}: base={result['base_score']:.4f}, "
            f"adjustment={result['content_adjustment']['total_adjustment']:+.6f}, "
            f"review_adjusted_score={result['review_adjusted_score']:.6f}, "
            f"mentioned={result['evidence_coverage']['mentioned_aspect_count']}/10"
        )
    raise SystemExit(not test_result.wasSuccessful())