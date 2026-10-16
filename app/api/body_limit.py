from collections.abc import Awaitable, Callable

from fastapi import Request, Response, status

from app.api.error_handlers import error_response

Middleware = Callable[[Request, Callable[[Request], Awaitable[Response]]], Awaitable[Response]]


def body_size_limit_middleware(max_body_bytes: int) -> Middleware:
    """Content-Length가 한도를 넘으면 본문을 읽기 전에 413으로 끊는다.

    의존성(Depends)에서 검사하면 이미 FastAPI가 multipart 본문 전체를 받은 뒤라 늦다.
    Content-Length 없이 chunked로 오는 요청은 여기서 막지 못하므로,
    최종 검증은 서비스가 실제 바이트 수로 한 번 더 한다.
    """

    async def middleware(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        content_length = request.headers.get("content-length", "")
        if content_length.isdigit() and int(content_length) > max_body_bytes:
            return error_response(
                status.HTTP_413_CONTENT_TOO_LARGE,
                "FILE_TOO_LARGE",
                "Request body exceeds the size limit.",
                {"max_body_bytes": max_body_bytes},
            )
        return await call_next(request)

    return middleware
