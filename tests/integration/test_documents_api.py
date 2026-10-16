import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.domain.document_status import DocumentStatus
from app.main import MULTIPART_OVERHEAD_BYTES
from app.models.audit_event import AuditEvent
from app.models.document import Document
from app.storage.file_storage import LocalFileStorage
from tests.factories import make_pdf
from tests.integration.conftest import MAX_UPLOAD_BYTES

BASE = "/api/v1/documents"


def upload(
    client: TestClient,
    data: bytes,
    filename: str = "contract.pdf",
    content_type: str = "application/pdf",
) -> Any:
    return client.post(BASE, files={"file": (filename, data, content_type)})


def create_document(client: TestClient, text: str = "contract") -> dict[str, Any]:
    response = upload(client, make_pdf([text]))
    assert response.status_code == 201, response.text
    return response.json()


# ---------- 업로드 ----------


def test_upload_pdf(client: TestClient, db_session: Session, storage: LocalFileStorage) -> None:
    data = make_pdf(["service agreement"])

    response = upload(client, data, filename="용역계약서.pdf")

    assert response.status_code == 201
    body = response.json()
    assert body["status"] == "UPLOADED"
    assert body["original_filename"] == "용역계약서.pdf"
    assert body["size_bytes"] == len(data)
    assert response.headers["Location"] == f"{BASE}/{body['id']}"

    document = db_session.get(Document, uuid.UUID(body["id"]))
    assert document is not None
    assert document.storage_key == f"{body['id']}.pdf"
    assert storage.path(document.storage_key).read_bytes() == data


def test_upload_records_audit_event(client: TestClient, db_session: Session) -> None:
    body = create_document(client)

    events = db_session.scalars(
        select(AuditEvent).where(AuditEvent.document_id == uuid.UUID(body["id"]))
    ).all()
    assert [e.action for e in events] == ["DOCUMENT_UPLOADED"]
    assert events[0].actor_type == "UNAUTHENTICATED_CLIENT"
    assert events[0].request_id is not None


def test_upload_rejects_non_pdf_even_with_pdf_extension(client: TestClient) -> None:
    response = upload(client, b"\x89PNG\r\n\x1a\nfake image", filename="image.pdf")
    assert response.status_code == 415
    assert response.json()["error"]["code"] == "UNSUPPORTED_MEDIA_TYPE"


def test_upload_rejects_empty_file(client: TestClient) -> None:
    response = upload(client, b"")
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "EMPTY_FILE"


def test_upload_rejects_file_over_limit(client: TestClient, settings: Settings) -> None:
    data = make_pdf(["x"]) + b"0" * MAX_UPLOAD_BYTES

    response = upload(client, data)

    assert response.status_code == 413
    assert response.json()["error"]["code"] == "FILE_TOO_LARGE"
    assert not list(settings.storage_dir.iterdir())  # 거절된 파일은 디스크에 남지 않는다


def test_oversized_request_is_rejected_before_body_is_parsed(
    client: TestClient, settings: Settings
) -> None:
    data = make_pdf(["x"]) + b"0" * (MAX_UPLOAD_BYTES + MULTIPART_OVERHEAD_BYTES)

    response = upload(client, data)

    assert response.status_code == 413
    error = response.json()["error"]
    assert error["code"] == "FILE_TOO_LARGE"
    assert "max_body_bytes" in error["details"]  # 서비스가 아니라 미들웨어가 거절했다는 표시
    assert response.headers["X-Request-ID"]
    assert not list(settings.storage_dir.iterdir())


def test_upload_rejects_duplicate_file(client: TestClient) -> None:
    data = make_pdf(["same"])
    first = upload(client, data).json()

    response = upload(client, data, filename="renamed.pdf")

    assert response.status_code == 409
    error = response.json()["error"]
    assert error["code"] == "DOCUMENT_ALREADY_EXISTS"
    assert error["details"] == {"existing_document_id": first["id"]}


def test_upload_requires_file_field(client: TestClient) -> None:
    response = client.post(BASE, data={"not_file": "x"})
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


def test_path_traversal_filename_never_reaches_disk(
    client: TestClient, db_session: Session, storage: LocalFileStorage
) -> None:
    body = upload(client, make_pdf(["traversal"]), filename="../../etc/passwd.pdf").json()

    assert body["original_filename"] == "passwd.pdf"
    document = db_session.get(Document, uuid.UUID(body["id"]))
    assert document is not None
    assert storage.path(document.storage_key).is_file()


# ---------- 조회 ----------


def test_get_document(client: TestClient) -> None:
    created = create_document(client)

    response = client.get(f"{BASE}/{created['id']}")

    assert response.status_code == 200
    assert response.json() == created


def test_get_missing_document_returns_404(client: TestClient) -> None:
    response = client.get(f"{BASE}/{uuid.uuid4()}")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "DOCUMENT_NOT_FOUND"


def test_list_documents_newest_first_with_pagination(
    client: TestClient, db_session: Session
) -> None:
    ids = [create_document(client, f"doc-{i}")["id"] for i in range(3)]
    # 테스트 전체가 바깥 트랜잭션 하나 안에서 돌기 때문에 PostgreSQL now()(=트랜잭션 시작 시각)가
    # 세 문서 모두 같다. 정렬을 검증하려면 시각을 명시적으로 벌려 준다.
    base_time = datetime(2026, 1, 1, tzinfo=UTC)
    for i, document_id in enumerate(ids):
        db_session.get(Document, uuid.UUID(document_id)).created_at = base_time + timedelta(  # type: ignore[union-attr]
            minutes=i
        )
    db_session.commit()

    page1 = client.get(BASE, params={"limit": 2, "offset": 0}).json()
    page2 = client.get(BASE, params={"limit": 2, "offset": 2}).json()

    assert page1["total"] == 3
    assert [d["id"] for d in page1["items"] + page2["items"]] == list(reversed(ids))


def test_list_documents_filters_by_status(client: TestClient, db_session: Session) -> None:
    uploaded = create_document(client, "a")
    failed = create_document(client, "b")
    db_session.get(Document, uuid.UUID(failed["id"])).status = DocumentStatus.FAILED  # type: ignore[union-attr]
    db_session.commit()

    body = client.get(BASE, params={"status": "FAILED"}).json()

    assert [d["id"] for d in body["items"]] == [failed["id"]]
    assert uploaded["id"] not in {d["id"] for d in body["items"]}


@pytest.mark.parametrize(
    "params", [{"limit": 101}, {"limit": 0}, {"offset": -1}, {"status": "DONE"}]
)
def test_list_documents_rejects_invalid_query(client: TestClient, params: dict[str, Any]) -> None:
    response = client.get(BASE, params=params)
    assert response.status_code == 422


# ---------- 삭제 ----------


def test_delete_document(
    client: TestClient, db_session: Session, storage: LocalFileStorage
) -> None:
    created = create_document(client)
    document = db_session.get(Document, uuid.UUID(created["id"]))
    assert document is not None

    response = client.delete(f"{BASE}/{created['id']}")

    assert response.status_code == 204
    assert client.get(f"{BASE}/{created['id']}").status_code == 404
    assert created["id"] not in {d["id"] for d in client.get(BASE).json()["items"]}
    assert not storage.exists(document.storage_key)
    db_session.refresh(document)
    assert document.deleted_at is not None  # 행은 소프트 삭제로 남는다


def test_delete_twice_returns_404(client: TestClient) -> None:
    created = create_document(client)
    assert client.delete(f"{BASE}/{created['id']}").status_code == 204
    assert client.delete(f"{BASE}/{created['id']}").status_code == 404


def test_same_file_can_be_uploaded_again_after_delete(client: TestClient) -> None:
    data = make_pdf(["reupload"])
    first = upload(client, data).json()
    client.delete(f"{BASE}/{first['id']}")

    response = upload(client, data)

    assert response.status_code == 201
    assert response.json()["id"] != first["id"]


def test_cannot_delete_document_while_processing(
    client: TestClient, db_session: Session, storage: LocalFileStorage
) -> None:
    created = create_document(client)
    document = db_session.get(Document, uuid.UUID(created["id"]))
    assert document is not None
    document.status = DocumentStatus.PROCESSING
    db_session.commit()

    response = client.delete(f"{BASE}/{created['id']}")

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "DOCUMENT_BUSY"
    assert storage.exists(document.storage_key)


# ---------- 이력 ----------


def test_history_lists_events_in_order(client: TestClient, db_session: Session) -> None:
    created = create_document(client)

    body = client.get(f"{BASE}/{created['id']}/history").json()

    assert body["total"] == 1
    event = body["items"][0]
    assert event["action"] == "DOCUMENT_UPLOADED"
    assert event["entity_type"] == "DOCUMENT"
    assert event["entity_id"] == created["id"]
    assert event["outcome"] == "SUCCESS"


def test_delete_is_recorded_and_history_is_hidden_afterwards(
    client: TestClient, db_session: Session
) -> None:
    created = create_document(client)
    client.delete(f"{BASE}/{created['id']}")

    actions = db_session.scalars(
        select(AuditEvent.action)
        .where(AuditEvent.document_id == uuid.UUID(created["id"]))
        .order_by(AuditEvent.id)
    ).all()
    assert actions == ["DOCUMENT_UPLOADED", "DOCUMENT_DELETED"]
    assert client.get(f"{BASE}/{created['id']}/history").status_code == 404
