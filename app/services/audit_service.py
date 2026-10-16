import uuid
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.logging import request_id_var
from app.domain.audit import ActorType, AuditAction, AuditOutcome, EntityType
from app.models.audit_event import AuditEvent


def record_event(
    db: Session,
    *,
    action: AuditAction,
    entity_type: EntityType,
    entity_id: uuid.UUID,
    document_id: uuid.UUID | None,
    actor_type: ActorType = ActorType.UNAUTHENTICATED_CLIENT,
    outcome: AuditOutcome = AuditOutcome.SUCCESS,
    changes: dict[str, Any] | None = None,
) -> AuditEvent:
    """감사 이벤트를 세션에 추가한다. 커밋하지 않는다.

    호출한 유스케이스와 같은 트랜잭션으로 커밋되므로
    '작업은 됐는데 이력이 없다' 또는 그 반대 상황이 생기지 않는다.
    """
    event = AuditEvent(
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        document_id=document_id,
        actor_type=actor_type,
        outcome=outcome,
        changes=changes,
        request_id=request_id_var.get(),
    )
    db.add(event)
    return event


def list_document_events(
    db: Session, document_id: uuid.UUID, *, limit: int, offset: int
) -> tuple[list[AuditEvent], int]:
    condition = AuditEvent.document_id == document_id
    total = db.scalar(select(func.count()).select_from(AuditEvent).where(condition)) or 0
    events = db.scalars(
        select(AuditEvent)
        .where(condition)
        .order_by(AuditEvent.occurred_at, AuditEvent.id)
        .limit(limit)
        .offset(offset)
    ).all()
    return list(events), total
