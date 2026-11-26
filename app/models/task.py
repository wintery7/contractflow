import uuid
from datetime import date, datetime

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.domain.task import TaskPriority, TaskSource, TaskStatus


def _in(values: type) -> str:
    return ", ".join(f"'{v.value}'" for v in values)


class Task(Base):
    __tablename__ = "tasks"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    document_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"))
    title: Mapped[str] = mapped_column(String(200))
    description: Mapped[str | None] = mapped_column(Text)
    priority: Mapped[str] = mapped_column(String(10), default=TaskPriority.MEDIUM)
    status: Mapped[str] = mapped_column(String(20), default=TaskStatus.TODO)
    assignee: Mapped[str | None] = mapped_column(String(100))
    due_date: Mapped[date | None] = mapped_column(Date)
    source: Mapped[str] = mapped_column(String(20), default=TaskSource.USER)
    source_analysis_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("document_analyses.id"))
    source_item_id: Mapped[str | None] = mapped_column(String(20))
    # 낙관적 잠금: 수정 요청이 가진 version과 DB의 version이 같을 때만 반영한다.
    version: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.clock_timestamp()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.clock_timestamp()
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        CheckConstraint(f"status IN ({_in(TaskStatus)})", name="status_valid"),
        CheckConstraint(f"priority IN ({_in(TaskPriority)})", name="priority_valid"),
        CheckConstraint(f"source IN ({_in(TaskSource)})", name="source_valid"),
        CheckConstraint("char_length(title) BETWEEN 1 AND 200", name="title_length"),
        CheckConstraint("version >= 1", name="version_positive"),
        # AI 제안에서 온 업무는 어떤 분석의 어떤 항목인지 반드시 남긴다.
        CheckConstraint(
            "(source = 'USER' AND source_analysis_id IS NULL AND source_item_id IS NULL)"
            " OR (source = 'AI_SUGGESTION' AND source_analysis_id IS NOT NULL"
            " AND source_item_id IS NOT NULL)",
            name="source_reference",
        ),
        CheckConstraint(
            "(status = 'DONE') = (completed_at IS NOT NULL)", name="completed_iff_done"
        ),
        # 같은 AI 제안을 두 번 업무로 등록하지 못하게 한다.
        Index(
            "uq_tasks_source_item",
            "source_analysis_id",
            "source_item_id",
            unique=True,
            postgresql_where=text("source_analysis_id IS NOT NULL"),
        ),
        Index("ix_tasks_document_status", "document_id", "status"),
        Index("ix_tasks_assignee_status", "assignee", "status"),
        Index(
            "ix_tasks_open_due_date",
            "due_date",
            postgresql_where=text("status IN ('TODO', 'IN_PROGRESS')"),
        ),
    )
