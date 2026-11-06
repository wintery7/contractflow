import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Query, Response, status

from app.api.deps import DbSession
from app.domain.task import TaskPriority, TaskStatus
from app.schemas.audit import AuditEventResponse
from app.schemas.common import ErrorResponse, Page
from app.schemas.task import TaskCreate, TaskResponse, TaskUpdate
from app.services import task_service

router = APIRouter(tags=["tasks"])

Limit = Annotated[int, Query(ge=1, le=100)]
Offset = Annotated[int, Query(ge=0)]


def _errors(*codes: int) -> dict[int | str, dict[str, Any]]:
    return {code: {"model": ErrorResponse} for code in codes}


@router.post(
    "/documents/{document_id}/tasks",
    response_model=TaskResponse,
    status_code=status.HTTP_201_CREATED,
    responses=_errors(400, 404, 409),
    summary="검토 업무 생성 (직접 입력 또는 AI 제안 승인)",
)
def create_task(
    document_id: uuid.UUID, body: TaskCreate, response: Response, db: DbSession
) -> TaskResponse:
    task = task_service.create_task(db, document_id, body)
    response.headers["Location"] = f"/api/v1/tasks/{task.id}"
    return TaskResponse.model_validate(task)


@router.get(
    "/documents/{document_id}/tasks",
    response_model=Page[TaskResponse],
    responses=_errors(404),
    summary="문서의 검토 업무 목록",
)
def list_tasks(
    document_id: uuid.UUID,
    db: DbSession,
    status_filter: Annotated[TaskStatus | None, Query(alias="status")] = None,
    priority: TaskPriority | None = None,
    assignee: Annotated[str | None, Query(max_length=100)] = None,
    limit: Limit = 20,
    offset: Offset = 0,
) -> Page[TaskResponse]:
    tasks, total = task_service.list_tasks(
        db,
        document_id,
        status=status_filter,
        priority=priority,
        assignee=assignee,
        limit=limit,
        offset=offset,
    )
    return Page[TaskResponse](
        items=[TaskResponse.model_validate(t) for t in tasks],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get(
    "/tasks/{task_id}", response_model=TaskResponse, responses=_errors(404), summary="업무 상세"
)
def get_task(task_id: uuid.UUID, db: DbSession) -> TaskResponse:
    return TaskResponse.model_validate(task_service.get_task(db, task_id))


@router.patch(
    "/tasks/{task_id}",
    response_model=TaskResponse,
    responses=_errors(404, 409, 422),
    summary="업무 수정 (상태·담당자·우선순위·기한, 완료 처리)",
)
def update_task(task_id: uuid.UUID, body: TaskUpdate, db: DbSession) -> TaskResponse:
    return TaskResponse.model_validate(task_service.update_task(db, task_id, body))


@router.get(
    "/tasks/{task_id}/history",
    response_model=Page[AuditEventResponse],
    responses=_errors(404),
    summary="업무 처리 이력",
)
def get_task_history(
    task_id: uuid.UUID, db: DbSession, limit: Limit = 20, offset: Offset = 0
) -> Page[AuditEventResponse]:
    events, total = task_service.list_task_events(db, task_id, limit=limit, offset=offset)
    return Page[AuditEventResponse](
        items=[AuditEventResponse.model_validate(e) for e in events],
        total=total,
        limit=limit,
        offset=offset,
    )
