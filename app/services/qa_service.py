"""계약서 질의응답 유스케이스.

근거 판단은 두 단계로 나뉜다.
1) 검색 단계: 최고 유사도가 임계값보다 낮으면 LLM을 호출하지 않는다 (비용·환각 방지)
2) 생성 단계: 모델이 '답할 수 없음'이라 하거나, 실제로 넘긴 청크를 인용하지 않으면
   답을 돌려주지 않는다
유사도 점수는 '주제가 비슷하다'는 뜻일 뿐 답의 정확성을 보장하지 않는다. 그래서 2)가 필요하다.
"""

import logging
import uuid
from dataclasses import dataclass
from enum import StrEnum

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import ConflictError, ServiceUnavailableError
from app.llm.base import LLMClient, LLMRequestRejectedError, LLMUnavailableError
from app.llm.embeddings import Embedder
from app.llm.structured import LLMCallRecord, StructuredOutputError
from app.models.document_chunk import DocumentChunk
from app.rag.answerer import QA_PROMPT_VERSION, chunk_label, generate_answer
from app.rag.indexer import embed_texts
from app.rag.retriever import RetrievedChunk, search_document
from app.services import document_service
from app.services.llm_call_log import record_llm_call

logger = logging.getLogger(__name__)


class AnswerStatus(StrEnum):
    ANSWERED = "ANSWERED"
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"


class InsufficientReason(StrEnum):
    LOW_RETRIEVAL_SCORE = "LOW_RETRIEVAL_SCORE"  # 검색 결과가 질문과 충분히 관련 없음
    MODEL_DECLINED = "MODEL_DECLINED"  # 모델이 발췌문만으로 답할 수 없다고 판단
    NO_VALID_CITATION = "NO_VALID_CITATION"  # 답은 했지만 실제 근거를 인용하지 않음


@dataclass(frozen=True)
class Citation:
    chunk: RetrievedChunk
    cited_by_answer: bool


@dataclass(frozen=True)
class QAResult:
    status: AnswerStatus
    reason: InsufficientReason | None
    answer: str | None
    citations: list[Citation]
    top_k: int
    max_score: float | None
    min_score: float


def _ensure_index(db: Session, document_id: uuid.UUID, embedding_model: str) -> None:
    models = db.scalars(
        select(DocumentChunk.embedding_model)
        .where(DocumentChunk.document_id == document_id)
        .group_by(DocumentChunk.embedding_model)
    ).all()
    if not models:
        raise ConflictError(
            "DOCUMENT_NOT_READY",
            "The document has not been indexed. Run an analysis first.",
        )
    if list(models) != [embedding_model]:
        # 다른 모델로 만든 벡터와는 거리를 비교할 수 없다.
        raise ConflictError(
            "INDEX_MODEL_MISMATCH",
            "The document was indexed with a different embedding model. Re-run the analysis.",
            {"indexed_with": list(models), "current": embedding_model},
        )


def _unavailable(code: str, exc: Exception) -> ServiceUnavailableError:
    return ServiceUnavailableError(
        code, "The language model service is unavailable.", {"reason": type(exc).__name__}
    )


def answer_question(
    db: Session,
    document_id: uuid.UUID,
    question: str,
    *,
    top_k: int,
    min_score: float,
    embedder: Embedder,
    llm: LLMClient,
) -> QAResult:
    document_service.get_document(db, document_id)
    _ensure_index(db, document_id, embedder.model)

    def log_call(purpose: str, provider: str, prompt_version: str | None):
        def record(call: LLMCallRecord) -> None:
            record_llm_call(
                db,
                purpose=purpose,
                provider=provider,
                record=call,
                prompt_version=prompt_version,
                document_id=document_id,
            )

        return record

    try:
        try:
            [query_vector] = embed_texts(
                embedder, [question], log_call("EMBEDDING", embedder.provider, None)
            )
        except (LLMUnavailableError, LLMRequestRejectedError) as exc:
            raise _unavailable("EMBEDDING_UNAVAILABLE", exc) from exc

        retrieved = search_document(db, document_id, query_vector, top_k=top_k)
        max_score = max((c.score for c in retrieved), default=None)

        if max_score is None or max_score < min_score:
            return QAResult(
                status=AnswerStatus.INSUFFICIENT_EVIDENCE,
                reason=InsufficientReason.LOW_RETRIEVAL_SCORE,
                answer=None,
                citations=[Citation(c, False) for c in retrieved],
                top_k=top_k,
                max_score=max_score,
                min_score=min_score,
            )

        try:
            output = generate_answer(
                question, retrieved, llm, log_call("QA_ANSWER", llm.provider, QA_PROMPT_VERSION)
            )
        except (LLMUnavailableError, LLMRequestRejectedError) as exc:
            raise _unavailable("LLM_UNAVAILABLE", exc) from exc
        except StructuredOutputError as exc:
            raise _unavailable("LLM_INVALID_OUTPUT", exc) from exc
    finally:
        # 성공·실패와 관계없이 LLM 호출 기록은 남긴다.
        db.commit()

    labels = {chunk_label(i): chunk for i, chunk in enumerate(retrieved)}
    cited = {label for label in output.cited_chunks if label in labels}
    citations = [Citation(c, chunk_label(i) in cited) for i, c in enumerate(retrieved)]

    if not output.answerable:
        status, reason, answer = (
            AnswerStatus.INSUFFICIENT_EVIDENCE,
            InsufficientReason.MODEL_DECLINED,
            None,
        )
    elif not cited:
        # 근거를 대지 못한 답은 돌려주지 않는다.
        status, reason, answer = (
            AnswerStatus.INSUFFICIENT_EVIDENCE,
            InsufficientReason.NO_VALID_CITATION,
            None,
        )
    else:
        status, reason, answer = AnswerStatus.ANSWERED, None, output.answer

    logger.info(
        "question answered",
        extra={
            "document_id": str(document_id),
            "status": status,
            "reason": reason,
            "max_score": max_score,
            "question_chars": len(question),
        },
    )
    return QAResult(
        status=status,
        reason=reason,
        answer=answer,
        citations=citations,
        top_k=top_k,
        max_score=max_score,
        min_score=min_score,
    )
