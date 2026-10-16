# Alembic autogenerate가 모든 테이블을 인식하도록 모델을 여기서 import 한다.
from app.models.audit_event import AuditEvent
from app.models.document import Document

__all__ = ["AuditEvent", "Document"]
