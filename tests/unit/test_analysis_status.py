import itertools

import pytest

from app.core.errors import InvalidStateTransitionError
from app.domain.analysis import AnalysisStatus, ensure_analysis_transition

S = AnalysisStatus
ALLOWED = {
    (S.QUEUED, S.RUNNING),
    (S.QUEUED, S.FAILED),
    (S.RUNNING, S.SUCCEEDED),
    (S.RUNNING, S.FAILED),
}


@pytest.mark.parametrize(("current", "target"), sorted(ALLOWED))
def test_allowed(current: S, target: S) -> None:
    assert ensure_analysis_transition(current, target) is target


@pytest.mark.parametrize(
    ("current", "target"), [p for p in itertools.product(S, S) if p not in ALLOWED]
)
def test_disallowed(current: S, target: S) -> None:
    # 끝난 분석(SUCCEEDED/FAILED)은 바뀌지 않는다. 재분석은 새 행을 만든다.
    with pytest.raises(InvalidStateTransitionError):
        ensure_analysis_transition(current, target)
