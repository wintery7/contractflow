"""검색 품질 실험 — 한 번에 한 변수만 바꾼다.

    uv run python -m evaluation.run_retrieval_eval

E1 청크 크기 → E2 겹침 → E3 top-k → E4 검색 방식(벡터/BM25/하이브리드) → 근거 부족 임계값 분석.
앞 단계에서 고른 값을 다음 단계의 고정값으로 쓴다. 선택 규칙: Recall@3이 가장 높은 설정,
같으면 MRR@10, 그래도 같으면 더 작은 값(비용이 적은 쪽).

결과는 evaluation/results/에 JSON과 Markdown으로 저장한다. 실행한 결과만 기록한다.
"""

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.core.config import Settings
from app.llm.embeddings import OpenAIEmbedder
from evaluation.dataset import Question, load_questions, validate
from evaluation.embedding_cache import CachedEmbedder
from evaluation.metrics import (
    evidence_coverage,
    first_relevant_rank,
    hit_at_k,
    mean,
    reciprocal_rank,
)
from evaluation.retrieval import METHODS, ContractIndex, build_indexes, rank, vector_scores

RESULTS_DIR = Path(__file__).parent / "results"
KS = (1, 3, 5, 8)
SIZES = (300, 500, 800, 1200)
OVERLAPS = (0, 50, 100, 200)
DEFAULT_OVERLAP = 100
THRESHOLDS = tuple(round(0.15 + 0.05 * i, 2) for i in range(10))  # 0.15 ~ 0.60


def evaluate(
    indexes: dict[str, ContractIndex],
    questions: list[Question],
    query_vectors: dict[str, list[float]],
    method: str,
) -> dict[str, Any]:
    targets = [q for q in questions if q.evidence]  # 근거가 있는 질문만 검색 지표 대상
    rows = []
    for q in targets:
        index = indexes[q.contract]
        order = rank(index, method, q.question, query_vectors[q.id])
        texts = [index.chunks[i].content for i in order]
        r = first_relevant_rank(texts, q.evidence)
        rows.append(
            {
                "id": q.id,
                "type": q.type,
                "rank": r,
                **{f"hit@{k}": hit_at_k(r, k) for k in KS},
                **{f"coverage@{k}": evidence_coverage(texts, q.evidence, k) for k in KS},
                "rr@10": reciprocal_rank(r, 10),
            }
        )
    summary = {
        **{f"recall@{k}": round(mean([row[f"hit@{k}"] for row in rows]), 3) for k in KS},
        **{f"coverage@{k}": round(mean([row[f"coverage@{k}"] for row in rows]), 3) for k in KS},
        "mrr@10": round(mean([row["rr@10"] for row in rows]), 3),
        "questions": len(rows),
        "avg_chunks_per_contract": round(mean([len(i.chunks) for i in indexes.values()]), 1),
        "avg_chunk_chars": round(
            mean([len(c.content) for i in indexes.values() for c in i.chunks]), 1
        ),
    }
    by_type: dict[str, list[float]] = {}
    for row in rows:
        by_type.setdefault(row["type"], []).append(row["hit@3"])
    summary["recall@3_by_type"] = {t: round(mean(v), 3) for t, v in sorted(by_type.items())}
    summary["misses@5"] = [row["id"] for row in rows if not row["hit@5"]]
    return summary


def pick(results: dict[Any, dict[str, Any]]) -> Any:
    return max(results, key=lambda key: (results[key]["recall@3"], results[key]["mrr@10"], -key))


def threshold_analysis(
    indexes: dict[str, ContractIndex],
    questions: list[Question],
    query_vectors: dict[str, list[float]],
) -> dict[str, Any]:
    """질문별 최고 유사도로 임계값마다 두 비율을 본다.

    '답할 수 있는 질문 통과율'과 '문서에 없는 질문 차단율'은 서로 맞바꾸는 관계다.
    """
    top = {q.id: max(vector_scores(indexes[q.contract], query_vectors[q.id])) for q in questions}
    answerable = [top[q.id] for q in questions if q.answerable is True]
    absent = [top[q.id] for q in questions if q.answerable is False]
    table = [
        {
            "threshold": t,
            "answerable_pass_rate": round(mean([s >= t for s in answerable]), 3),
            "not_in_doc_block_rate": round(mean([s < t for s in absent]), 3),
        }
        for t in THRESHOLDS
    ]
    return {
        "answerable_top1_score": {
            "min": round(min(answerable), 3),
            "mean": round(mean(answerable), 3),
        },
        "not_in_doc_top1_score": {"max": round(max(absent), 3), "mean": round(mean(absent), 3)},
        "table": table,
    }


def to_markdown(report: dict[str, Any]) -> str:
    lines = [
        f"# 검색 평가 결과 ({report['run_at']})",
        "",
        f"- 임베딩 모델: `{report['embedding_model']}`, 질문 {report['questions']['total']}개 "
        f"(검색 지표 대상 {report['questions']['with_evidence']}개)",
        "",
    ]

    def table(title: str, rows: dict[Any, dict[str, Any]], label: str) -> None:
        lines.extend(
            [
                f"## {title}",
                "",
                f"| {label} | Recall@1 | Recall@3 | Recall@5 | MRR@10 | Coverage@5 "
                "| 청크 수(평균) |",
                "|---|---|---|---|---|---|---|",
            ]
        )
        for key, r in rows.items():
            lines.append(
                f"| {key} | {r['recall@1']} | {r['recall@3']} | {r['recall@5']} | "
                f"{r['mrr@10']} | {r['coverage@5']} | {r['avg_chunks_per_contract']} |"
            )
        lines.append("")

    e = report["experiments"]
    table(f"E1 청크 크기 (overlap={DEFAULT_OVERLAP}, vector)", e["E1_chunk_size"], "max_chars")
    table(
        f"E2 겹침 (max_chars={report['chosen']['max_chars']}, vector)", e["E2_overlap"], "overlap"
    )
    lines.extend(["## E3 top-k", "", "| k | Recall@k | Coverage@k |", "|---|---|---|"])
    for k, r in e["E3_top_k"].items():
        lines.append(f"| {k} | {r['recall']} | {r['coverage']} |")
    lines.append("")
    table("E4 검색 방식", e["E4_method"], "method")
    lines.extend(
        [
            "## 근거 부족 임계값 (vector top-1 유사도)",
            "",
            "| threshold | 답할 수 있는 질문 통과율 | 문서에 없는 질문 차단율 |",
            "|---|---|---|",
        ]
    )
    for row in report["threshold"]["table"]:
        lines.append(
            f"| {row['threshold']} | {row['answerable_pass_rate']} "
            f"| {row['not_in_doc_block_rate']} |"
        )
    lines.append("")
    return "\n".join(lines)


def main() -> None:
    questions = load_questions()
    if errors := validate(questions):
        raise SystemExit("dataset errors:\n" + "\n".join(errors))

    settings = Settings()
    if settings.openai_api_key is None:
        raise SystemExit("OPENAI_API_KEY is required")
    embedder = CachedEmbedder(
        OpenAIEmbedder(
            api_key=settings.openai_api_key.get_secret_value(),
            model=settings.embedding_model,
            dimensions=settings.embedding_dimensions,
            timeout=60,
            max_retries=2,
        )
    )
    query_vectors = dict(
        zip([q.id for q in questions], embedder.embed([q.question for q in questions]), strict=True)
    )

    def run(max_chars: int, overlap: int, method: str = "vector") -> dict[str, Any]:
        indexes = build_indexes(embedder, max_chars=max_chars, overlap_chars=overlap)
        return evaluate(indexes, questions, query_vectors, method)

    e1 = {size: run(size, min(DEFAULT_OVERLAP, size // 3)) for size in SIZES}
    size = pick(e1)
    e2 = {overlap: run(size, overlap) for overlap in OVERLAPS if overlap < size}
    overlap = pick(e2)
    best = e2[overlap]
    e3 = {k: {"recall": best[f"recall@{k}"], "coverage": best[f"coverage@{k}"]} for k in KS}
    e4 = {method: run(size, overlap, method) for method in METHODS}
    indexes = build_indexes(embedder, max_chars=size, overlap_chars=overlap)

    report = {
        "run_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "embedding_model": settings.embedding_model,
        "questions": {
            "total": len(questions),
            "with_evidence": sum(1 for q in questions if q.evidence),
        },
        "selection_rule": "max Recall@3, then MRR@10, then smaller value",
        "chosen": {"max_chars": size, "overlap_chars": overlap},
        "experiments": {
            "E1_chunk_size": e1,
            "E2_overlap": e2,
            "E3_top_k": e3,
            "E4_method": e4,
        },
        "threshold": threshold_analysis(indexes, questions, query_vectors),
        "embedding_api": {"calls": embedder.api_calls, "texts": embedder.api_texts},
    }

    RESULTS_DIR.mkdir(exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    (RESULTS_DIR / f"retrieval-{stamp}.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    markdown = to_markdown(report)
    (RESULTS_DIR / "retrieval-latest.md").write_text(markdown, encoding="utf-8")
    print(markdown)


if __name__ == "__main__":
    main()
