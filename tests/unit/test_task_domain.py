import itertools
from typing import Any

import pytest
from pydantic import ValidationError

from app.core.errors import InvalidStateTransitionError
from app.domain.task import TaskStatus, ensure_task_transition
from app.schemas.task import TaskCreate, TaskUpdate

S = TaskStatus
ALLOWED = {
    (S.TODO, S.IN_PROGRESS),
    (S.TODO, S.CANCELED),
    (S.IN_PROGRESS, S.TODO),
    (S.IN_PROGRESS, S.DONE),
    (S.IN_PROGRESS, S.CANCELED),
    (S.DONE, S.IN_PROGRESS),
    (S.CANCELED, S.TODO),
}


@pytest.mark.parametrize(("current", "target"), sorted(ALLOWED))
def test_allowed_transitions(current: S, target: S) -> None:
    assert ensure_task_transition(current, target) is target


@pytest.mark.parametrize(
    ("current", "target"), [p for p in itertools.product(S, S) if p not in ALLOWED]
)
def test_disallowed_transitions(current: S, target: S) -> None:
    with pytest.raises(InvalidStateTransitionError):
        ensure_task_transition(current, target)


def test_create_requires_title_without_source() -> None:
    with pytest.raises(ValidationError):
        TaskCreate()
    assert TaskCreate(title="  해지 조항 검토  ").title == "해지 조항 검토"


def test_create_from_suggestion_may_omit_title() -> None:
    data = TaskCreate.model_validate(
        {"source": {"analysis_id": "00000000-0000-0000-0000-000000000001", "review_item_id": "r1"}}
    )
    assert data.title is None


@pytest.mark.parametrize(
    "body",
    [
        {"version": 1},  # 바꿀 필드가 없음
        {"version": 1, "title": None},
        {"version": 1, "status": None},
        {"version": 0, "status": "DONE"},
        {"version": 1, "unknown": "x"},
    ],
)
def test_invalid_updates(body: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        TaskUpdate.model_validate(body)


def test_explicit_null_clears_optional_fields() -> None:
    data = TaskUpdate.model_validate({"version": 2, "assignee": None, "due_date": None})
    assert data.requested_changes() == {"assignee": None, "due_date": None}
