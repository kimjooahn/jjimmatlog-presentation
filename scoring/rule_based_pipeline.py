"""Run the full review scoring pipeline using local Korean lexical rules only."""
from __future__ import annotations

import argparse
import asyncio
from pathlib import Path

from scoring.ai_review_pipeline import (
    CACHE_PATH,
    DATA_DIRECTORY,
    RESULTS_CSV_PATH,
    REVIEWER_WEIGHTS_CSV_PATH,
    RESTAURANT_SCORES_CSV_PATH,
    load_source_reviews,
    print_full_statistics,
    print_reviewer_and_restaurant_statistics,
    process_reviews,
    read_cache,
    select_result_entries,
    write_cache,
    write_results_csv,
)
from scoring.restaurant_aggregation import build_restaurant_scores, write_restaurant_scores_csv, write_reviewer_weights_csv
from scoring.reviewer_weight import compute_reviewer_weights
from scoring.rule_based_review_analyzer import RuleBasedReviewAnalyzer


def main() -> int:
    parser = argparse.ArgumentParser(description="로컬 키워드 규칙으로 전체 리뷰 분석 및 점수 계산")
    parser.add_argument("--data-dir", type=Path, default=DATA_DIRECTORY)
    parser.add_argument("--cache", type=Path, default=CACHE_PATH)
    parser.add_argument("--csv-output", type=Path, default=RESULTS_CSV_PATH)
    args = parser.parse_args()

    reviews = load_source_reviews(args.data_dir)
    if not reviews:
        print("분석할 리뷰가 없습니다.")
        return 2

    analyzer = RuleBasedReviewAnalyzer()
    cache = read_cache(args.cache, expected_provider="rule_based")
    asyncio.run(process_reviews(reviews, cache, analyzer, args.cache, provider="rule_based"))
    entries = select_result_entries(reviews, cache)
    write_cache(args.cache, cache, analyzer.model, provider="rule_based")
    write_results_csv(args.csv_output, entries)

    reviewer_rows, weights_by_reviewer_id = compute_reviewer_weights(reviews, entries)
    write_reviewer_weights_csv(REVIEWER_WEIGHTS_CSV_PATH, reviewer_rows)
    restaurant_rows, restaurant_details = build_restaurant_scores(reviews, entries, weights_by_reviewer_id)
    write_restaurant_scores_csv(RESTAURANT_SCORES_CSV_PATH, restaurant_rows)

    print(f"전체 리뷰 수: {len(reviews)}")
    print_full_statistics(entries)
    print_reviewer_and_restaurant_statistics(reviewer_rows, restaurant_rows, restaurant_details)
    print(
        "\n생성 결과:"
        f"\n분석 JSON: {args.cache}"
        f"\n리뷰 점수 CSV: {args.csv_output}"
        f"\n리뷰어 가중치 CSV: {REVIEWER_WEIGHTS_CSV_PATH}"
        f"\n식당 점수 CSV: {RESTAURANT_SCORES_CSV_PATH}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())