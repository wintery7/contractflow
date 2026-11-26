import uuid
from datetime import date, datetime
from typing import Any, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.domain.task import TaskPriority, TaskSource, TaskStatus

_UPDATABLE_NON_NULL = {"title", "priority", "status"}


class TaskSourceRef(BaseModel):
    analysis_id: uuid.UUID
    review_item_id: str = Field(pattern=r"^r\d{1,3}$", examples=["r1"])


class TaskCreate(BaseModel):
    """source가 있으면 AI 제안을 승인하는 것이고, 비운 필드는 제안 내용으로 채운다."""

    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    title: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=5000)
    priority: TaskPriority | None = None
    assignee: str | None = Field(default=None, min_length=1, max_length=100)
    due_date: date | None = None
    source: TaskSourceRef | None = None

    @model_validator(mode="after")
    def _title_or_source(self) -> Self:
        if self.source is None and self.title is None:
            raise ValueError("title is required unless the task is created from an AI suggestion")
        return self


class TaskUpdate(BaseModel):
    """보낸 필드만 바꾼다(PATCH). version은 마지막으로 읽은 값을 그대로 보내야 한다."""

    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    version: int = Field(ge=1)
    title: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=5000)
    priority: TaskPriority | None = None
    status: TaskStatus | None = None
    assignee: str | None = Field(default=None, min_length=1, max_length=100)
    due_date: date | None = None

    @model_validator(mode="after")
    def _has_changes(self) -> Self:
        fields = self.model_fields_set - {"version"}
        if not fields:
            raise ValueError("at least one field to update is required")
        for name in fields & _UPDATABLE_NON_NULL:
            if getattr(self, name) is None:
                raise ValueError(f"{name} cannot be null")
        return self

    def requested_changes(self) -> dict[str, Any]:
        # null을 명시적으로 보낸 필드(assignee, due_date 등)는 '비우기'로 해석한다.
        return {name: getattr(self, name) for name in self.model_fields_set - {"version"}}


class TaskResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    document_id: uuid.UUID
    title: str
    description: str | None
    priority: TaskPriority
    status: TaskStatus
    assignee: str | None
    due_date: date | None
    source: TaskSource
    source_analysis_id: uuid.UUID | None
    source_item_id: str | None
    version: int
    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None
