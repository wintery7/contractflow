"""검토 업무(Task)의 상태 머신과 값 정의."""

from enum import StrEnum

from app.core.errors import InvalidStateTransitionError


class TaskStatus(StrEnum):
    TODO = "TODO"
    IN_PROGRESS = "IN_PROGRESS"
    DONE = "DONE"
    CANCELED = "CANCELED"


class TaskPriority(StrEnum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


class TaskSource(StrEnum):
    USER = "USER"
    # AI가 제안한 검토 항목을 사용자가 승인해 만든 업무. AI가 직접 만들지는 않는다.
    AI_SUGGESTION = "AI_SUGGESTION"


ALLOWED_TRANSITIONS: dict[TaskStatus, frozenset[TaskStatus]] = {
    TaskStatus.TODO: frozenset({TaskStatus.IN_PROGRESS, TaskStatus.CANCELED}),
    TaskStatus.IN_PROGRESS: frozenset({TaskStatus.TODO, TaskStatus.DONE, TaskStatus.CANCELED}),
    # 완료 후 문제가 다시 발견되면 재개
    TaskStatus.DONE: frozenset({TaskStatus.IN_PROGRESS}),
    # 실수로 취소한 업무 복구
    TaskStatus.CANCELED: frozenset({TaskStatus.TODO}),
}


def ensure_task_transition(current: TaskStatus, target: TaskStatus) -> TaskStatus:
    if target not in ALLOWED_TRANSITIONS[current]:
        raise InvalidStateTransitionError("Task", current, target)
    return target
