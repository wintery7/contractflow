import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import BigInteger, CheckConstraint, DateTime, Identity, Index, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.domain.audit import ActorType, AuditOutcome, EntityType


def _in(values: type) -> str:
    return ", ".join(f"'{v.value}'" for v in values)


class AuditEvent(Base):
    """append-only 감사 이벤트.

    document_id에 FK를 걸지 않는다: 문서가 영구 삭제(purge)되어도 이력은 남아야 하기 때문.
    changes에는 허용 목록에 있는 필드의 before/after만 기록하고 원문은 저장하지 않는다.
    """

    __tablename__ = "audit_events"

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    actor_type: Mapped[str] = mapped_column(String(30))
    action: Mapped[str] = mapped_column(String(50))
    entity_type: Mapped[str] = mapped_column(String(20))
    entity_id: Mapped[uuid.UUID]
    document_id: Mapped[uuid.UUID | None]
    outcome: Mapped[str] = mapped_column(String(10))
    changes: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    request_id: Mapped[str | None] = mapped_column(String(64))

    __table_args__ = (
        CheckConstraint(f"actor_type IN ({_in(ActorType)})", name="actor_type_valid"),
        CheckConstraint(f"entity_type IN ({_in(EntityType)})", name="entity_type_valid"),
        CheckConstraint(f"outcome IN ({_in(AuditOutcome)})", name="outcome_valid"),
        Index("ix_audit_events_document_id_occurred_at", "document_id", "occurred_at"),
        Index("ix_audit_events_entity_occurred_at", "entity_type", "entity_id", "occurred_at"),
    )
