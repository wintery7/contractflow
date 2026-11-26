"""DB 없이 검증 가능한 API 공통 동작: 오류 형식, 요청 ID, 헬스체크."""

import json
import logging

import pytest
from fastapi.testclient import TestClient

from app.api.error_handlers import status_for
from app.core.errors import (
    AppError,
    BadRequestError,
    ConflictError,
    InvalidStateTransitionError,
    NotFoundError,
    PayloadTooLargeError,
    UnsupportedMediaTypeError,
)
from app.core.logging import JsonFormatter, mask_secrets
from app.main import create_app


@pytest.fixture
def client() -> TestClient:
    return TestClient(create_app())


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (BadRequestError("C", "m"), 400),
        (NotFoundError("C", "m"), 404),
        (ConflictError("C", "m"), 409),
        (PayloadTooLargeError("C", "m"), 413),
        (UnsupportedMediaTypeError("C", "m"), 415),
        (InvalidStateTransitionError("Task", "DONE", "TODO"), 422),
        (AppError("C", "m"), 500),
    ],
)
def test_error_status_mapping(error: AppError, expected: int) -> None:
    assert status_for(error) == expected


def test_app_error_uses_common_error_format() -> None:
    app = create_app()

    @app.get("/boom")
    def boom() -> None:
        raise ConflictError("SOMETHING_CONFLICTS", "conflict!", {"id": "1"})

    response = TestClient(app).get("/boom")

    assert response.status_code == 409
    body = response.json()["error"]
    assert body["code"] == "SOMETHING_CONFLICTS"
    assert body["details"] == {"id": "1"}
    assert body["request_id"] == response.headers["X-Request-ID"]


def test_unexpected_error_hides_internals() -> None:
    app = create_app()

    @app.get("/crash")
    def crash() -> None:
        raise RuntimeError("secret internal detail")

    response = TestClient(app, raise_server_exceptions=False).get("/crash")

    assert response.status_code == 500
    assert response.json()["error"]["code"] == "INTERNAL_ERROR"
    assert "secret internal detail" not in response.text


def test_unknown_route_uses_common_error_format(client: TestClient) -> None:
    response = client.get("/nope")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "HTTP_404"


def test_validation_error_does_not_echo_input(client: TestClient) -> None:
    response = client.get("/api/v1/documents/not-a-uuid-SENSITIVE")
    assert response.status_code == 422
    body = response.json()["error"]
    assert body["code"] == "VALIDATION_ERROR"
    assert "SENSITIVE" not in response.text


def test_health_live(client: TestClient) -> None:
    response = client.get("/health/live")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_request_id_is_generated(client: TestClient) -> None:
    response = client.get("/health/live")
    assert len(response.headers["X-Request-ID"]) == 32


def test_valid_incoming_request_id_is_propagated(client: TestClient) -> None:
    response = client.get("/health/live", headers={"X-Request-ID": "trace-123"})
    assert response.headers["X-Request-ID"] == "trace-123"


def test_malformed_incoming_request_id_is_replaced(client: TestClient) -> None:
    response = client.get("/health/live", headers={"X-Request-ID": "bad id\twith spaces"})
    assert response.headers["X-Request-ID"] != "bad id\twith spaces"


def test_secrets_are_masked_in_logs() -> None:
    assert mask_secrets("key=sk-proj-abcdefghijklmnop") == "key=sk-***"

    record = logging.makeLogRecord(
        {"msg": "calling api with sk-abcdefghijklmnopqrstuvwx", "levelname": "INFO"}
    )
    payload = json.loads(JsonFormatter().format(record))
    assert "abcdefghijklmnop" not in payload["message"]


def test_extra_fields_are_included_in_json_log() -> None:
    record = logging.makeLogRecord({"msg": "done", "document_id": "d-1", "duration_ms": 12.5})
    payload = json.loads(JsonFormatter().format(record))
    assert payload["document_id"] == "d-1"
    assert payload["duration_ms"] == 12.5
