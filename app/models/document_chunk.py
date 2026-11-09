import uuid
from datetime import datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base

EMBEDDING_DIMENSIONS = 1536


class DocumentChunk(Base):
    """검색 단위 청크와 임베딩.

    검색은 항상 '한 문서 안'에서 일어난다(수십~수백 청크). 그래서 ANN 인덱스(HNSW) 대신
    (document_id, chunk_index) 유니크 인덱스로 후보를 좁힌 뒤 정확한 코사인 거리를 계산한다.
    HNSW에 document_id 필터를 걸면 인덱스 탐색 후 필터링 때문에 결과가 k개보다 적어질 수 있다.
    """

    __tablename__ = "document_chunks"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    document_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"))
    chunk_index: Mapped[int] = mapped_column(Integer)
    page_start: Mapped[int] = mapped_column(Integer)
    page_end: Mapped[int] = mapped_column(Integer)
    content: Mapped[str] = mapped_column(Text)
    embedding: Mapped[list[float]] = mapped_column(Vector(EMBEDDING_DIMENSIONS))
    # 모델을 바꾸면 벡터 공간이 달라지므로 어떤 모델로 만든 벡터인지 남긴다.
    embedding_model: Mapped[str] = mapped_column(String(100))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.clock_timestamp()
    )

    __table_args__ = (
        UniqueConstraint("document_id", "chunk_index"),
        CheckConstraint("chunk_index >= 0", name="chunk_index_non_negative"),
        CheckConstraint("page_start >= 1 AND page_start <= page_end", name="page_range_valid"),
    )
