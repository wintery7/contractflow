"""문서 상태 머신.

documents.status는 '가장 최근 분석 실행'의 요약 상태다.
허용 전이를 한곳에 모아 두면 서비스 코드 곳곳에서 if문으로 상태를 바꾸는 일을 막을 수 있다.
"""

from enum import StrEnum

from app.core.errors import InvalidStateTransitionError


class DocumentStatus(StrEnum):
    UPLOADED = "UPLOADED"
    PROCESSING = "PROCESSING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


ALLOWED_TRANSITIONS: dict[DocumentStatus, frozenset[DocumentStatus]] = {
    DocumentStatus.UPLOADED: frozenset({DocumentStatus.PROCESSING}),
    DocumentStatus.PROCESSING: frozenset({DocumentStatus.COMPLETED, DocumentStatus.FAILED}),
    # 실패 후 재시도
    DocumentStatus.FAILED: frozenset({DocumentStatus.PROCESSING}),
    # 모델/프롬프트 변경 후 재분석
    DocumentStatus.COMPLETED: frozenset({DocumentStatus.PROCESSING}),
}


def can_transition(current: DocumentStatus, target: DocumentStatus) -> bool:
    return target in ALLOWED_TRANSITIONS[current]


def ensure_transition(current: DocumentStatus, target: DocumentStatus) -> DocumentStatus:
    if not can_transition(current, target):
        raise InvalidStateTransitionError("Document", current, target)
    return target
