import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, String, func, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.domain.analysis import AnalysisStatus

_STATUS_VALUES = ", ".join(f"'{s.value}'" for s in AnalysisStatus)


class DocumentAnalysis(Base):
    """분석 실행 1회. 문서 1 : 분석 N (재분석해도 이전 결과를 보존한다)."""

    __tablename__ = "document_analyses"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    document_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"))
    status: Mapped[str] = mapped_column(String(20), default=AnalysisStatus.QUEUED)
    stage: Mapped[str | None] = mapped_column(String(30))
    pipeline_version: Mapped[str] = mapped_column(String(30))
    llm_model: Mapped[str] = mapped_column(String(100))
    prompt_version: Mapped[str] = mapped_column(String(30))
    result: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    error_code: Mapped[str | None] = mapped_column(String(50))
    error_message: Mapped[str | None] = mapped_column(String(500))
    # now()는 '트랜잭션 시작 시각'이라 한 트랜잭션 안의 행끼리 같아진다.
    # '가장 최근 분석'을 시각으로 고르므로 실제 삽입 시각인 clock_timestamp()를 쓴다.
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.clock_timestamp()
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # 실행 중 주기적으로 갱신. 오래 갱신되지 않은 RUNNING은 중단된 작업으로 본다.
    heartbeat_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.clock_timestamp()
    )

    __table_args__ = (
        CheckConstraint(f"status IN ({_STATUS_VALUES})", name="status_valid"),
        CheckConstraint(
            "(status = 'SUCCEEDED') = (result IS NOT NULL)", name="result_iff_succeeded"
        ),
        CheckConstraint("(status = 'FAILED') = (error_code IS NOT NULL)", name="error_iff_failed"),
        # 문서당 '진행 중' 분석은 하나만. 애플리케이션의 if문이 아니라 DB가 보장한다.
        Index(
            "uq_document_analyses_in_progress",
            "document_id",
            unique=True,
            postgresql_where=text("status IN ('QUEUED', 'RUNNING')"),
        ),
        Index("ix_document_analyses_document_created_at", "document_id", text("created_at DESC")),
    )
