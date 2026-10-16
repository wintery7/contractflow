from typing import Any, Generic, TypeVar

from pydantic import BaseModel

T = TypeVar("T")


# Python 3.11이라 PEP 695(class Page[T]) 문법 대신 Generic을 쓴다.
class Page(BaseModel, Generic[T]):
    items: list[T]
    total: int
    limit: int
    offset: int


class ErrorBody(BaseModel):
    code: str
    message: str
    details: dict[str, Any] | None = None
    request_id: str | None = None


class ErrorResponse(BaseModel):
    error: ErrorBody
