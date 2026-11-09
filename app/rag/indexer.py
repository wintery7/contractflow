"""색인: 청크 → 임베딩 → document_chunks 저장."""

import time
import uuid

from sqlalchemy import delete
from sqlalchemy.orm import Session

from app.llm.base import LLMRequestRejectedError, LLMUnavailableError
from app.llm.embeddings import Embedder
from app.llm.structured import LLMCallRecord, OnCall, elapsed_ms, error_code_for
from app.models.document_chunk import DocumentChunk
from app.pipeline.chunker import Chunk


def embed_texts(embedder: Embedder, texts: list[str], on_call: OnCall) -> list[list[float]]:
    """임베딩을 만들고 호출을 기록한다. 실패는 기록한 뒤 그대로 올린다."""
    started = time.perf_counter()
    try:
        result = embedder.embed(texts)
    except (LLMUnavailableError, LLMRequestRejectedError) as exc:
        on_call(
            LLMCallRecord(
                model=embedder.model,
                attempt=1,
                status="ERROR",
                latency_ms=elapsed_ms(started),
                error_code=error_code_for(exc),
            )
        )
        raise
    on_call(
        LLMCallRecord(
            model=embedder.model,
            attempt=1,
            status="SUCCESS",
            latency_ms=elapsed_ms(started),
            input_tokens=result.input_tokens,
        )
    )
    if len(result.vectors) != len(texts):
        raise LLMUnavailableError("embedding count mismatch")
    return result.vectors


def replace_chunks(
    db: Session,
    document_id: uuid.UUID,
    chunks: list[Chunk],
    vectors: list[list[float]],
    embedding_model: str,
) -> None:
    """문서의 기존 청크를 지우고 새로 넣는다 (같은 트랜잭션). 커밋은 호출한 쪽이 한다."""
    db.execute(delete(DocumentChunk).where(DocumentChunk.document_id == document_id))
    db.add_all(
        DocumentChunk(
            document_id=document_id,
            chunk_index=chunk.index,
            page_start=chunk.page_start,
            page_end=chunk.page_end,
            content=chunk.content,
            embedding=vector,
            embedding_model=embedding_model,
        )
        for chunk, vector in zip(chunks, vectors, strict=True)
    )
