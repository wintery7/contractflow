"""문서 범위 벡터 검색.

한 문서의 청크(수십~수백 개)만 대상으로 정확한 코사인 거리를 계산한다.
ANN 인덱스가 없으므로 근사 오차도, 필터링으로 결과가 k개보다 줄어드는 문제도 없다.
"""

import uuid
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.document_chunk import DocumentChunk


@dataclass(frozen=True)
class RetrievedChunk:
    chunk_id: uuid.UUID
    chunk_index: int
    page_start: int
    page_end: int
    content: str
    # 코사인 유사도(1 - 코사인 거리). '주제가 비슷하다'는 신호일 뿐 답의 정확성을 뜻하지 않는다.
    score: float


def search_document(
    db: Session, document_id: uuid.UUID, query_vector: list[float], *, top_k: int
) -> list[RetrievedChunk]:
    distance = DocumentChunk.embedding.cosine_distance(query_vector).label("distance")
    rows = db.execute(
        select(DocumentChunk, distance)
        .where(DocumentChunk.document_id == document_id)
        .order_by(distance, DocumentChunk.chunk_index)
        .limit(top_k)
    ).all()
    return [
        RetrievedChunk(
            chunk_id=chunk.id,
            chunk_index=chunk.chunk_index,
            page_start=chunk.page_start,
            page_end=chunk.page_end,
            content=chunk.content,
            score=round(1.0 - float(dist), 4),
        )
        for chunk, dist in rows
    ]
