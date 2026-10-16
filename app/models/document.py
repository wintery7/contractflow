import uuid
from datetime import datetime

from sqlalchemy import BigInteger, CheckConstraint, DateTime, Index, Integer, String, func, text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.domain.document_status import DocumentStatus

_STATUS_VALUES = ", ".join(f"'{s.value}'" for s in DocumentStatus)


class Document(Base):
    __tablename__ = "documents"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    original_filename: Mapped[str] = mapped_column(String(255))
    content_type: Mapped[str] = mapped_column(String(100))
    size_bytes: Mapped[int] = mapped_column(BigInteger)
    sha256: Mapped[str] = mapped_column(String(64))
    storage_key: Mapped[str] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(String(20), default=DocumentStatus.UPLOADED)
    page_count: Mapped[int | None] = mapped_column(Integer)
    error_code: Mapped[str | None] = mapped_column(String(50))
    error_message: Mapped[str | None] = mapped_column(String(500))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        CheckConstraint("size_bytes > 0", name="size_positive"),
        CheckConstraint("char_length(sha256) = 64", name="sha256_length"),
        CheckConstraint(f"status IN ({_STATUS_VALUES})", name="status_valid"),
        CheckConstraint("page_count IS NULL OR page_count >= 0", name="page_count_non_negative"),
        # 삭제되지 않은 문서 중에서만 같은 파일 중복을 막는다 (삭제 후 재업로드는 허용).
        Index(
            "uq_documents_sha256_active",
            "sha256",
            unique=True,
            postgresql_where=text("deleted_at IS NULL"),
        ),
        Index(
            "ix_documents_active_created_at",
            text("created_at DESC"),
            postgresql_where=text("deleted_at IS NULL"),
        ),
        Index(
            "ix_documents_active_status_created_at",
            "status",
            text("created_at DESC"),
            postgresql_where=text("deleted_at IS NULL"),
        ),
    )
