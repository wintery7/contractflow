import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict

from app.domain.document_status import DocumentStatus


class DocumentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    original_filename: str
    size_bytes: int
    status: DocumentStatus
    page_count: int | None
    error_code: str | None
    created_at: datetime
    updated_at: datetime
