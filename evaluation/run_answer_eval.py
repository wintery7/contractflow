"""답변 품질·지연 평가 — 검색부터 답변 생성까지 실제 모델로 실행한다.

    uv run python -m evaluation.run_answer_eval --top-k 5 --min-score 0.3

판정 규칙은 서비스와 같은 함수(qa_service.resolve_answer)를 쓴다.

지표
- 답할 수 있는 질문(answerable=true): 답변률, 근거 인용 적중률(인용한 청크에 정답 근거 포함),
  키워드 일치율(정답 핵심 표현이 답에 모두 포함 — 표기만 다른 정답도 틀림으로 세는 엄격한 기준)
- 문서에 없는 질문(answerable=false): 거절률. 답해 버리면 '근거 없는 주장'
- 근거 없는 주장 발생률
  = (문서에 없는 질문에 답한 수 + 정답 근거를 인용하지 못한 답 수) / 전체 답변 수
- 지연: 질문 임베딩 + 검색 + 답변 생성 전체 (ms). 평균, p50, p95
- 모호한 질문(answerable=null)은 정확도 집계에서 빼고 동작만 기록한다
"""

import argparse
import json
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.core.config import Settings
from app.llm.base import LLMError
from app.llm.embeddings import OpenAIEmbedder
from app.llm.openai_client import OpenAIClient
from app.llm.structured import LLMCallRecord, StructuredOutputError
from app.rag.answerer import chunk_label, generate_answer
from app.rag.retriever import RetrievedChunk
from app.services.qa_service import AnswerStatus, resolve_answer
from evaluation.dataset import load_questions, validate
from evaluation.embedding_cache import CachedEmbedder
from evaluation.metrics import is_relevant, mean, percentile, squash
from evaluation.retrieval import build_indexes, rank, vector_scores

RESULTS_DIR = Path(__file__).parent / "results"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--max-chars", type=int, default=500)
    parser.add_argument("--overlap", type=int, default=100)
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--min-score", type=float, default=0.3)
    parser.add_argument("--method", choices=["vector", "hybrid"], default="vector")
    args = parser.parse_args()

    questions = load_questions()
    if errors := validate(questions):
        raise SystemExit("dataset errors:\n" + "\n".join(errors))
    settings = Settings()
    if settings.openai_api_key is None:
        raise SystemExit("OPENAI_API_KEY is required")
    key = settings.openai_api_key.get_secret_value()
    raw_embedder = OpenAIEmbedder(
        api_key=key,
        model=settings.embedding_model,
        dimensions=settings.embedding_dimensions,
        timeout=60,
        max_retries=2,
    )
    llm = OpenAIClient(
        api_key=key,
        model=settings.llm_model,
        timeout=settings.llm_timeout_seconds,
        max_retries=settings.llm_max_retries,
    )
    indexes = build_indexes(
        CachedEmbedder(raw_embedder), max_chars=args.max_chars, overlap_chars=args.overlap
    )

    rows: list[dict[str, Any]] = []
    for q in questions:
        index = indexes[q.contract]
        calls: list[LLMCallRecord] = []
        started = time.perf_counter()
        error = None
        status, reason, answer, cited_relevant = None, None, None, False
        try:
            # 지연을 실제와 같게 재기 위해 질문 임베딩은 캐시하지 않는다.
            [query_vector] = raw_embedder.embed([q.question]).vectors
            scores = vector_scores(index, query_vector)
            order = rank(index, args.method, q.question, query_vector)[: args.top_k]
            retrieved = [
                RetrievedChunk(
                    chunk_id=None,  # type: ignore[arg-type]
                    chunk_index=index.chunks[i].index,
                    page_start=index.chunks[i].page_start,
                    page_end=index.chunks[i].page_end,
                    content=index.chunks[i].content,
                    score=round(scores[i], 4),
                )
                for i in order
            ]
            max_score = max(c.score for c in retrieved)
            if max_score < args.min_score:
                status, reason = AnswerStatus.INSUFFICIENT_EVIDENCE, "LOW_RETRIEVAL_SCORE"
            else:
                output = generate_answer(q.question, retrieved, llm, calls.append)
                status, reason_enum, answer, cited = resolve_answer(output, len(retrieved))
                reason = reason_enum.value if reason_enum else None
                cited_texts = [
                    c.content for i, c in enumerate(retrieved) if chunk_label(i) in cited
                ]
                cited_relevant = any(is_relevant(t, q.evidence) for t in cited_texts)
        except (LLMError, StructuredOutputError) as exc:
            error = type(exc).__name__
        latency_ms = round((time.perf_counter() - started) * 1000)
        answered = status == AnswerStatus.ANSWERED
        rows.append(
            {
                "id": q.id,
                "type": q.type,
                "answerable": q.answerable,
                "status": status.value if status else None,
                "reason": reason,
                "answered": answered,
                "cited_relevant": cited_relevant,
                "keyword_match": bool(
                    answered and answer and all(squash(k) in squash(answer) for k in q.keywords)
                ),
                "latency_ms": latency_ms,
                "llm_calls": len(calls),
                "input_tokens": sum(c.input_tokens or 0 for c in calls),
                "output_tokens": sum(c.output_tokens or 0 for c in calls),
                "error": error,
                "answer": answer,
            }
        )
        print(f"{q.id} {q.type:15} {rows[-1]['status']} {reason or ''} {latency_ms}ms")

    answerable = [r for r in rows if r["answerable"] is True]
    absent = [r for r in rows if r["answerable"] is False]
    answered = [r for r in rows if r["answered"] and r["answerable"] is not None]
    ungrounded = [r for r in answered if r["answerable"] is False or not r["cited_relevant"]]
    latencies = [r["latency_ms"] for r in rows if r["error"] is None]
    summary = {
        "answerable": {
            "count": len(answerable),
            "answered_rate": round(mean([r["answered"] for r in answerable]), 3),
            "citation_hit_rate": round(mean([r["cited_relevant"] for r in answerable]), 3),
            "keyword_match_rate": round(mean([r["keyword_match"] for r in answerable]), 3),
        },
        "not_in_doc": {
            "count": len(absent),
            "refusal_rate": round(mean([not r["answered"] for r in absent]), 3),
        },
        "ungrounded_answer_rate": round(len(ungrounded) / len(answered), 3) if answered else 0.0,
        "latency_ms": {
            "mean": round(mean(latencies)),
            "p50": round(percentile(latencies, 50)),
            "p95": round(percentile(latencies, 95)),
            "max": max(latencies) if latencies else 0,
        },
        "error_rate": round(mean([r["error"] is not None for r in rows]), 3),
        "tokens": {
            "input": sum(r["input_tokens"] for r in rows),
            "output": sum(r["output_tokens"] for r in rows),
        },
        "ambiguous": [
            {"id": r["id"], "status": r["status"], "reason": r["reason"]}
            for r in rows
            if r["answerable"] is None
        ],
    }
    report = {
        "run_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "llm_model": settings.llm_model,
        "embedding_model": settings.embedding_model,
        "config": vars(args),
        "summary": summary,
        "rows": rows,
    }
    RESULTS_DIR.mkdir(exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    (RESULTS_DIR / f"answers-{stamp}.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
