"""분석 실행(document_analyses)의 상태·단계·오류 코드."""

from enum import StrEnum

from app.core.errors import InvalidStateTransitionError

# 분석 로직(추출·정제·프롬프트 구성)이 바뀌면 올린다. 같은 버전·모델·프롬프트로 이미 성공한
# 분석이 있으면 재사용하고, 하나라도 다르면 새로 분석한다.
PIPELINE_VERSION = "m2-v1"


class AnalysisStatus(StrEnum):
    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"


IN_PROGRESS_STATUSES = frozenset({AnalysisStatus.QUEUED, AnalysisStatus.RUNNING})


class AnalysisStage(StrEnum):
    """실패 지점을 추적하기 위한 실행 단계. M3에서 CHUNKING/EMBEDDING/INDEXING이 추가된다."""

    EXTRACTING = "EXTRACTING"
    FIELD_EXTRACTION = "FIELD_EXTRACTION"


class AnalysisErrorCode(StrEnum):
    PDF_UNREADABLE = "PDF_UNREADABLE"
    PDF_ENCRYPTED = "PDF_ENCRYPTED"
    NO_TEXT_LAYER = "NO_TEXT_LAYER"
    DOCUMENT_TOO_LARGE = "DOCUMENT_TOO_LARGE"
    FILE_MISSING = "FILE_MISSING"
    LLM_UNAVAILABLE = "LLM_UNAVAILABLE"
    LLM_REQUEST_REJECTED = "LLM_REQUEST_REJECTED"
    LLM_INVALID_OUTPUT = "LLM_INVALID_OUTPUT"
    LLM_NOT_CONFIGURED = "LLM_NOT_CONFIGURED"
    INTERRUPTED = "INTERRUPTED"
    INTERNAL_ERROR = "INTERNAL_ERROR"


class AnalysisFailure(Exception):
    """분석을 FAILED로 끝내야 하는 '예상된' 실패.

    code는 API로 노출되고 message는 내부 정보가 없는 정제된 설명이다.
    """

    def __init__(self, code: AnalysisErrorCode, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


_ALLOWED: dict[AnalysisStatus, frozenset[AnalysisStatus]] = {
    AnalysisStatus.QUEUED: frozenset({AnalysisStatus.RUNNING, AnalysisStatus.FAILED}),
    AnalysisStatus.RUNNING: frozenset({AnalysisStatus.SUCCEEDED, AnalysisStatus.FAILED}),
    # 끝난 분석은 바뀌지 않는다. 재분석은 새 행을 만든다(이력 보존).
    AnalysisStatus.SUCCEEDED: frozenset(),
    AnalysisStatus.FAILED: frozenset(),
}


def ensure_analysis_transition(current: AnalysisStatus, target: AnalysisStatus) -> AnalysisStatus:
    if target not in _ALLOWED[current]:
        raise InvalidStateTransitionError("Analysis", current, target)
    return target
