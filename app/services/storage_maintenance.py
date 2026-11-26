"""저장소 정리: DB가 가리키지 않는 원본 파일(고아 파일)을 찾는다.

고아 파일이 생기는 경우
- 업로드 중 '파일 저장 → DB 커밋' 사이에 프로세스가 죽은 경우
- 문서 삭제 후 파일 삭제가 실패한 경우 (삭제 API는 커밋 후 파일 삭제를 시도하고 실패해도 성공 처리)
"""

import logging

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.document import Document
from app.storage.file_storage import FileStorage

logger = logging.getLogger(__name__)


def find_orphan_keys(db: Session, storage: FileStorage) -> list[str]:
    """삭제되지 않은 문서가 참조하지 않는 저장 키 목록."""
    referenced = set(
        db.scalars(select(Document.storage_key).where(Document.deleted_at.is_(None))).all()
    )
    return [key for key in storage.list_keys() if key not in referenced]


def delete_orphans(db: Session, storage: FileStorage) -> list[str]:
    orphans = find_orphan_keys(db, storage)
    for key in orphans:
        storage.delete(key)
    logger.info("deleted orphan files", extra={"count": len(orphans)})
    return orphans
