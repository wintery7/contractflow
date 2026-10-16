"""모든 오류를 {"error": {code, message, details, request_id}} 한 가지 형식으로 변환한다."""

import logging
from typing import Any

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.errors import (
    AppError,
    BadRequestError,
    ConflictError,
    InvalidStateTransitionError,
    NotFoundError,
    PayloadTooLargeError,
    UnsupportedMediaTypeError,
)
from app.core.logging import request_id_var

logger = logging.getLogger(__name__)

# 도메인 예외 종류 → HTTP 상태 코드 (서비스 계층은 HTTP를 모른다)
STATUS_BY_ERROR: dict[type[AppError], int] = {
    BadRequestError: status.HTTP_400_BAD_REQUEST,
    NotFoundError: status.HTTP_404_NOT_FOUND,
    ConflictError: status.HTTP_409_CONFLICT,
    PayloadTooLargeError: status.HTTP_413_CONTENT_TOO_LARGE,
    UnsupportedMediaTypeError: status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
    InvalidStateTransitionError: status.HTTP_422_UNPROCESSABLE_CONTENT,
}


def status_for(error: AppError) -> int:
    for error_type in type(error).__mro__:
        if error_type in STATUS_BY_ERROR:
            return STATUS_BY_ERROR[error_type]
    return status.HTTP_500_INTERNAL_SERVER_ERROR


def error_response(
    status_code: int,
    code: str,
    message: str,
    details: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
) -> JSONResponse:
    body = {
        "error": {
            "code": code,
            "message": message,
            "details": details,
            "request_id": request_id_var.get(),
        }
    }
    return JSONResponse(status_code=status_code, content=body, headers=headers)


async def handle_app_error(_: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, AppError)
    return error_response(status_for(exc), exc.code, exc.message, exc.details)


async def handle_validation_error(_: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, RequestValidationError)
    # 'input'은 사용자가 보낸 원본 값이므로 응답에 되돌려 주지 않는다.
    errors = [
        {"loc": list(err.get("loc", ())), "msg": err.get("msg"), "type": err.get("type")}
        for err in exc.errors()
    ]
    return error_response(
        status.HTTP_422_UNPROCESSABLE_CONTENT,
        "VALIDATION_ERROR",
        "Request validation failed.",
        {"errors": errors},
    )


async def handle_http_exception(_: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, StarletteHTTPException)
    return error_response(
        exc.status_code,
        f"HTTP_{exc.status_code}",
        str(exc.detail),
        headers=getattr(exc, "headers", None),
    )


async def handle_unexpected_error(_: Request, exc: Exception) -> JSONResponse:
    # 스택트레이스는 로그에만 남기고 클라이언트에는 노출하지 않는다.
    logger.error("unhandled error", exc_info=exc)
    return error_response(
        status.HTTP_500_INTERNAL_SERVER_ERROR, "INTERNAL_ERROR", "Internal server error."
    )


def register_error_handlers(app: FastAPI) -> None:
    app.add_exception_handler(AppError, handle_app_error)
    app.add_exception_handler(RequestValidationError, handle_validation_error)
    app.add_exception_handler(StarletteHTTPException, handle_http_exception)
    app.add_exception_handler(Exception, handle_unexpected_error)
