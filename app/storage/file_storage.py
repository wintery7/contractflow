"""원본 파일 저장소.

서비스는 FileStorage 프로토콜에만 의존한다. 지금은 로컬 디스크 구현만 있고,
운영 환경으로 옮길 때 같은 인터페이스로 S3/MinIO 구현을 추가한다.
"""

import os
import re
import shutil
import tempfile
from pathlib import Path
from typing import BinaryIO, Protocol

# 저장 키는 서버가 만든 "<uuid>.pdf"만 허용한다 → 경로 조작이 원천적으로 불가능.
_KEY_PATTERN = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\.pdf$")


class InvalidStorageKeyError(ValueError):
    pass


class FileStorage(Protocol):
    def save(self, key: str, source: BinaryIO) -> None: ...

    def delete(self, key: str) -> None: ...

    def exists(self, key: str) -> bool: ...

    def path(self, key: str) -> Path: ...


class LocalFileStorage:
    def __init__(self, root: Path) -> None:
        self._root = root.resolve()
        self._root.mkdir(parents=True, exist_ok=True)

    def path(self, key: str) -> Path:
        if not _KEY_PATTERN.match(key):
            raise InvalidStorageKeyError(f"invalid storage key: {key!r}")
        return self._root / key

    def save(self, key: str, source: BinaryIO) -> None:
        target = self.path(key)
        # 임시 파일에 다 쓴 뒤 rename → 중간에 실패해도 반쯤 쓰인 파일이 남지 않는다.
        fd, tmp_name = tempfile.mkstemp(dir=self._root, suffix=".tmp")
        try:
            with os.fdopen(fd, "wb") as tmp:
                shutil.copyfileobj(source, tmp)
            os.replace(tmp_name, target)
        except BaseException:
            Path(tmp_name).unlink(missing_ok=True)
            raise

    def delete(self, key: str) -> None:
        self.path(key).unlink(missing_ok=True)

    def exists(self, key: str) -> bool:
        return self.path(key).is_file()
