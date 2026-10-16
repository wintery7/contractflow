import io
import uuid
from pathlib import Path

import pytest

from app.storage.file_storage import InvalidStorageKeyError, LocalFileStorage


@pytest.fixture
def storage(tmp_path: Path) -> LocalFileStorage:
    return LocalFileStorage(tmp_path / "uploads")


def test_save_exists_delete(storage: LocalFileStorage) -> None:
    key = f"{uuid.uuid4()}.pdf"
    storage.save(key, io.BytesIO(b"%PDF-1.4 data"))

    assert storage.exists(key)
    assert storage.path(key).read_bytes() == b"%PDF-1.4 data"

    storage.delete(key)
    assert not storage.exists(key)
    storage.delete(key)  # 이미 없는 파일 삭제는 오류가 아니다 (재시도 안전)


def test_save_leaves_no_temp_files(storage: LocalFileStorage, tmp_path: Path) -> None:
    storage.save(f"{uuid.uuid4()}.pdf", io.BytesIO(b"x"))
    assert not list((tmp_path / "uploads").glob("*.tmp"))


@pytest.mark.parametrize(
    "key",
    ["../escape.pdf", "contract.pdf", f"{uuid.uuid4()}.exe", f"sub/{uuid.uuid4()}.pdf", ""],
)
def test_rejects_keys_that_are_not_server_generated(storage: LocalFileStorage, key: str) -> None:
    with pytest.raises(InvalidStorageKeyError):
        storage.path(key)
