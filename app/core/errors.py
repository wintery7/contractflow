"""애플리케이션 예외 계층.

서비스/도메인 계층은 HTTP를 모른다. 여기서는 '어떤 종류의 실패인가'만 표현하고,
HTTP 상태 코드로의 변환은 api/error_handlers.py가 담당한다.
"""

from typing import Any


class AppError(Exception):
    def __init__(self, code: str, message: str, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details


class BadRequestError(AppError):
    pass


class NotFoundError(AppError):
    pass


class ConflictError(AppError):
    pass


class PayloadTooLargeError(AppError):
    pass


class UnsupportedMediaTypeError(AppError):
    pass


class ServiceUnavailableError(AppError):
    pass


class InvalidStateTransitionError(AppError):
    def __init__(self, entity: str, current: str, target: str) -> None:
        super().__init__(
            code="INVALID_STATE_TRANSITION",
            message=f"{entity} cannot move from {current} to {target}.",
            details={"from": current, "to": target},
        )
