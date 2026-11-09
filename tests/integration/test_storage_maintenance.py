import io
import uuid

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.services.storage_maintenance import delete_orphans, find_orphan_keys
from app.storage.file_storage import LocalFileStorage
from tests.factories import make_pdf


def upload(client: TestClient, text: str) -> str:
    response = client.post(
        "/api/v1/documents", files={"file": ("a.pdf", make_pdf([text]), "application/pdf")}
    )
    return str(response.json()["id"])


def test_finds_files_not_referenced_by_active_documents(
    client: TestClient, db_session: Session, storage: LocalFileStorage
) -> None:
    kept = upload(client, "kept")
    deleted = upload(client, "deleted")
    client.delete(f"/api/v1/documents/{deleted}")
    # 커밋 전에 프로세스가 죽어 DB 행 없이 남은 파일을 흉내 낸다
    crashed_key = f"{uuid.uuid4()}.pdf"
    storage.save(crashed_key, io.BytesIO(b"%PDF-1.4 orphan"))
    # 삭제 API가 파일 삭제에 실패한 경우를 흉내 낸다
    leftover_key = f"{deleted}.pdf"
    storage.save(leftover_key, io.BytesIO(b"%PDF-1.4 leftover"))

    orphans = find_orphan_keys(db_session, storage)

    assert sorted(orphans) == sorted([crashed_key, leftover_key])
    assert f"{kept}.pdf" not in orphans


def test_delete_orphans_keeps_referenced_files(
    client: TestClient, db_session: Session, storage: LocalFileStorage
) -> None:
    kept = upload(client, "kept")
    orphan_key = f"{uuid.uuid4()}.pdf"
    storage.save(orphan_key, io.BytesIO(b"%PDF-1.4 orphan"))

    assert delete_orphans(db_session, storage) == [orphan_key]
    assert storage.list_keys() == [f"{kept}.pdf"]
