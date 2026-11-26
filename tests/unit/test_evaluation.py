"""평가 데이터와 지표 계산이 올바른지 (네트워크 없이) 확인한다."""

import pytest

from evaluation.dataset import load_questions, validate
from evaluation.lexical import BM25, rank_by, reciprocal_rank_fusion
from evaluation.metrics import (
    evidence_coverage,
    first_relevant_rank,
    hit_at_k,
    percentile,
    reciprocal_rank,
)


def test_dataset_is_valid_and_large_enough() -> None:
    questions = load_questions()
    assert validate(questions) == []
    assert len(questions) >= 30
    assert {q.type for q in questions} == {
        "fact",
        "location",
        "multi",
        "not_in_doc",
        "ambiguous",
        "similar_clause",
    }


def test_rank_metrics() -> None:
    ranked = ["제1조 목적", "제2조 계약기간은 2026년", "제3조 금액"]
    rank = first_relevant_rank(ranked, ["계약기간은 2026년"])
    assert rank == 2
    assert hit_at_k(rank, 1) == 0.0
    assert hit_at_k(rank, 3) == 1.0
    assert reciprocal_rank(rank, 10) == 0.5
    assert reciprocal_rank(None, 10) == 0.0


def test_relevance_ignores_whitespace_and_line_breaks() -> None:
    assert (
        first_relevant_rank(["금 3,000,000원을\n다음 달 15일까지"], ["3,000,000원을 다음 달"]) == 1
    )


def test_evidence_coverage_counts_each_snippet() -> None:
    ranked = ["A 14일 이내", "B 기타", "C 30일 전에"]
    assert evidence_coverage(ranked, ["14일 이내", "30일 전에"], 1) == 0.5
    assert evidence_coverage(ranked, ["14일 이내", "30일 전에"], 3) == 1.0


def test_percentile_matches_linear_interpolation() -> None:
    assert percentile([10, 20, 30, 40], 50) == 25
    assert percentile([10, 20, 30, 40], 95) == pytest.approx(38.5)


def test_bm25_prefers_documents_sharing_terms() -> None:
    bm25 = BM25(["비밀유지 의무는 3년간", "계약기간은 2026년 12월 31일까지", "지체상금"])
    assert rank_by(bm25.scores("계약기간은 언제까지"))[0] == 1


def test_rrf_rewards_items_ranked_high_by_both() -> None:
    assert reciprocal_rank_fusion([[2, 0, 1], [2, 1, 0]])[0] == 2
