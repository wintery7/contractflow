"""검토 업무 유스케이스: 생성(직접 / AI 제안 승인), 조회, 수정(낙관적 잠금), 이력."""

import uuid
from datetime import UTC, date, datetime
from typing import Any

from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.errors import BadRequestError, ConflictError, NotFoundError
from app.domain.analysis import AnalysisStatus
from app.domain.audit import AuditAction, EntityType
from app.domain.task import TaskPriority, TaskSource, TaskStatus, ensure_task_transition
from app.models.audit_event import AuditEvent
from app.models.document import Document
from app.models.document_analysis import DocumentAnalysis
from app.models.task import Task
from app.schemas.task import TaskCreate, TaskSourceRef, TaskUpdate
from app.services import audit_service, document_service


def _audit_value(value: Any) -> Any:
    return value.isoformat() if isinstance(value, date) else value


def _find_review_item(
    db: Session, document_id: uuid.UUID, source: TaskSourceRef
) -> tuple[DocumentAnalysis, dict[str, Any]]:
    analysis = db.get(DocumentAnalysis, source.analysis_id)
    if analysis is None or analysis.document_id != document_id:
        raise NotFoundError("ANALYSIS_NOT_FOUND", "Analysis not found for this document.")
    if analysis.status != AnalysisStatus.SUCCEEDED or analysis.result is None:
        raise ConflictError("ANALYSIS_NOT_SUCCEEDED", "The analysis has no result to accept.")
    for item in analysis.result.get("review_items", []):
        if item.get("item_id") == source.review_item_id:
            return analysis, item
    raise BadRequestError(
        "REVIEW_ITEM_NOT_FOUND",
        "The review item does not exist in this analysis.",
        {"review_item_id": source.review_item_id},
    )


def _existing_task_for_item(db: Session, source: TaskSourceRef) -> Task | None:
    return db.scalar(
        select(Task).where(
            Task.source_analysis_id == source.analysis_id,
            Task.source_item_id == source.review_item_id,
        )
    )


def _duplicate_suggestion(task: Task) -> ConflictError:
    return ConflictError(
        "TASK_ALREADY_EXISTS",
        "A task has already been created from this suggestion.",
        {"task_id": str(task.id)},
    )


def create_task(db: Session, document_id: uuid.UUID, data: TaskCreate) -> Task:
    document_service.get_document(db, document_id)

    title, description, priority = data.title, data.description, data.priority
    source = TaskSource.USER
    if data.source is not None:
        # AI 제안 승인: 사용자가 비운 필드는 제안 내용으로 채운다.
        _, item = _find_review_item(db, document_id, data.source)
        if existing := _existing_task_for_item(db, data.source):
            raise _duplicate_suggestion(existing)
        title = title or item["title"][:200]
        description = description if description is not None else item.get("reason")
        priority = priority or TaskPriority(item["priority"])
        source = TaskSource.AI_SUGGESTION

    task = Task(
        id=uuid.uuid4(),
        document_id=document_id,
        title=title,
        description=description,
        priority=priority or TaskPriority.MEDIUM,
        status=TaskStatus.TODO,
        assignee=data.assignee,
        due_date=data.due_date,
        source=source,
        source_analysis_id=data.source.analysis_id if data.source else None,
        source_item_id=data.source.review_item_id if data.source else None,
        version=1,
    )
    db.add(task)
    audit_service.record_event(
        db,
        action=AuditAction.TASK_CREATED,
        entity_type=EntityType.TASK,
        entity_id=task.id,
        document_id=document_id,
        changes={
            "source": source,
            "source_item_id": task.source_item_id,
            "priority": task.priority,
            "assignee": task.assignee,
            "due_date": _audit_value(task.due_date),
        },
    )
    try:
        db.commit()
    except IntegrityError:
        # 같은 제안을 동시에 승인한 경우: 부분 유니크 인덱스가 하나만 통과시킨다.
        db.rollback()
        if data.source and (existing := _existing_task_for_item(db, data.source)):
            raise _duplicate_suggestion(existing) from None
        raise
    return task


def get_task(db: Session, task_id: uuid.UUID) -> Task:
    # 삭제된 문서의 업무는 노출하지 않는다.
    task = db.scalar(
        select(Task)
        .join(Document, Document.id == Task.document_id)
        .where(Task.id == task_id, Document.deleted_at.is_(None))
    )
    if task is None:
        raise NotFoundError("TASK_NOT_FOUND", "Task not found.")
    return task


def list_tasks(
    db: Session,
    document_id: uuid.UUID,
    *,
    status: TaskStatus | None,
    priority: TaskPriority | None,
    assignee: str | None,
    limit: int,
    offset: int,
) -> tuple[list[Task], int]:
    document_service.get_document(db, document_id)
    conditions = [Task.document_id == document_id]
    if status is not None:
        conditions.append(Task.status == status)
    if priority is not None:
        conditions.append(Task.priority == priority)
    if assignee is not None:
        conditions.append(Task.assignee == assignee)

    total = db.scalar(select(func.count()).select_from(Task).where(*conditions)) or 0
    tasks = db.scalars(
        select(Task)
        .where(*conditions)
        .order_by(Task.created_at, Task.id)
        .limit(limit)
        .offset(offset)
    ).all()
    return list(tasks), total


def update_task(db: Session, task_id: uuid.UUID, data: TaskUpdate) -> Task:
    """낙관적 잠금으로 수정한다.

    1) 읽은 version이 현재 version과 다르면 누군가 먼저 고친 것이므로 409
    2) 실제 UPDATE도 'WHERE version = 읽은 값' 조건으로 실행해, 읽은 뒤 끼어든 수정까지 막는다
    행 잠금(SELECT FOR UPDATE)을 오래 잡지 않아 동시 사용자가 많아도 대기가 생기지 않는다.
    """
    task = get_task(db, task_id)
    if task.version != data.version:
        raise _version_conflict(task.version)

    changes: dict[str, dict[str, Any]] = {}
    values: dict[str, Any] = {}
    for name, new_value in data.requested_changes().items():
        old_value = getattr(task, name)
        if old_value == new_value:
            continue
        if name == "status":
            ensure_task_transition(TaskStatus(old_value), new_value)
            if new_value == TaskStatus.DONE:
                values["completed_at"] = datetime.now(UTC)
            elif old_value == TaskStatus.DONE:
                values["completed_at"] = None
        values[name] = new_value
        changes[name] = {"from": _audit_value(old_value), "to": _audit_value(new_value)}

    if not values:
        return task  # 바뀐 것이 없으면 version을 올리지 않는다 (멱등)

    result = db.execute(
        update(Task)
        .where(Task.id == task.id, Task.version == data.version)
        .values(**values, version=Task.version + 1, updated_at=func.clock_timestamp())
        .execution_options(synchronize_session=False)
    )
    if result.rowcount == 0:  # type: ignore[attr-defined]
        db.rollback()
        raise _version_conflict(get_task(db, task_id).version)

    audit_service.record_event(
        db,
        action=AuditAction.TASK_UPDATED,
        entity_type=EntityType.TASK,
        entity_id=task.id,
        document_id=task.document_id,
        changes=changes,
    )
    db.commit()
    db.refresh(task)
    return task


def _version_conflict(current_version: int) -> ConflictError:
    return ConflictError(
        "VERSION_CONFLICT",
        "The task was modified by someone else. Reload it and try again.",
        {"current_version": current_version},
    )


def list_task_events(
    db: Session, task_id: uuid.UUID, *, limit: int, offset: int
) -> tuple[list[AuditEvent], int]:
    get_task(db, task_id)
    condition = (AuditEvent.entity_type == EntityType.TASK) & (AuditEvent.entity_id == task_id)
    total = db.scalar(select(func.count()).select_from(AuditEvent).where(condition)) or 0
    events = db.scalars(
        select(AuditEvent)
        .where(condition)
        .order_by(AuditEvent.occurred_at, AuditEvent.id)
        .limit(limit)
        .offset(offset)
    ).all()
    return list(events), total
