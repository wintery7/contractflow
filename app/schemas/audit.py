import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict

from app.domain.audit import ActorType, AuditOutcome, EntityType


class AuditEventResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    occurred_at: datetime
    actor_type: ActorType
    action: str
    entity_type: EntityType
    entity_id: uuid.UUID
    outcome: AuditOutcome
    changes: dict[str, Any] | None
