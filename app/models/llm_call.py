import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class LlmCall(Base):
    """LLM 호출 메타데이터 (운영 지표: 지연·토큰·실패율). 프롬프트·응답 본문은 저장하지 않는다."""

    __tablename__ = "llm_calls"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    purpose: Mapped[str] = mapped_column(String(30))
    provider: Mapped[str] = mapped_column(String(30))
    model: Mapped[str] = mapped_column(String(100))
    prompt_version: Mapped[str | None] = mapped_column(String(30))
    analysis_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("document_analyses.id", ondelete="SET NULL")
    )
    document_id: Mapped[uuid.UUID | None]
    attempt: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(20))
    latency_ms: Mapped[int] = mapped_column(Integer)
    input_tokens: Mapped[int | None] = mapped_column(Integer)
    output_tokens: Mapped[int | None] = mapped_column(Integer)
    error_code: Mapped[str | None] = mapped_column(String(50))

    __table_args__ = (
        CheckConstraint(
            "purpose IN ('FIELD_EXTRACTION', 'QA_ANSWER', 'EMBEDDING')", name="purpose_valid"
        ),
        CheckConstraint("status IN ('SUCCESS', 'ERROR', 'INVALID_OUTPUT')", name="status_valid"),
        CheckConstraint("attempt >= 1", name="attempt_positive"),
        CheckConstraint("latency_ms >= 0", name="latency_non_negative"),
        Index("ix_llm_calls_occurred_at", "occurred_at"),
        Index("ix_llm_calls_purpose_occurred_at", "purpose", "occurred_at"),
        Index("ix_llm_calls_analysis_id", "analysis_id"),
    )
