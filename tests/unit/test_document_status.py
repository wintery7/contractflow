import itertools

import pytest

from app.core.errors import InvalidStateTransitionError
from app.domain.document_status import DocumentStatus, can_transition, ensure_transition

S = DocumentStatus

ALLOWED = {
    (S.UPLOADED, S.PROCESSING),
    (S.PROCESSING, S.COMPLETED),
    (S.PROCESSING, S.FAILED),
    (S.FAILED, S.PROCESSING),
    (S.COMPLETED, S.PROCESSING),
}
ALL_PAIRS = list(itertools.product(S, S))


@pytest.mark.parametrize(("current", "target"), sorted(ALLOWED))
def test_allowed_transitions(current: S, target: S) -> None:
    assert can_transition(current, target)
    assert ensure_transition(current, target) is target


@pytest.mark.parametrize(("current", "target"), [p for p in ALL_PAIRS if p not in ALLOWED])
def test_disallowed_transitions_raise(current: S, target: S) -> None:
    assert not can_transition(current, target)
    with pytest.raises(InvalidStateTransitionError) as exc_info:
        ensure_transition(current, target)
    assert exc_info.value.details == {"from": current, "to": target}


def test_every_status_has_transition_rule() -> None:
    from app.domain.document_status import ALLOWED_TRANSITIONS

    assert set(ALLOWED_TRANSITIONS) == set(S)
