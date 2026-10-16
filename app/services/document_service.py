"""문서 업로드/조회/삭제 유스케이스.

트랜잭션 경계는 이 계층이 갖는다: 함수 하나가 유스케이스 하나이고, 성공하면 커밋한다.
"""

import hashlib
import logging
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import BinaryIO

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.errors import (
    BadRequestError,
    ConflictError,
    NotFoundError,
    PayloadTooLargeError,
    UnsupportedMediaTypeError,
)
from app.domain.audit import AuditAction, EntityType
from app.domain.document_status import DocumentStatus
from app.domain.filename import sanitize_filename
from app.models.document import Document
from app.services import audit_service
from app.storage.file_storage import FileStorage

logger = logging.getLogger(__name__)

PDF_MAGIC = b"%PDF-"
PDF_CONTENT_TYPE = "application/pdf"
_READ_CHUNK = 64 * 1024


@dataclass(frozen=True)
class FileInspection:
    size_bytes: int
    sha256: str


def inspect_pdf(source: BinaryIO, max_bytes: int) -> FileInspection:
    """파일을 청크 단위로 읽으며 크기·해시·매직 바이트를 검증한다.

    확장자나 클라이언트가 보낸 Content-Type은 쉽게 위조되므로 믿지 않고,
    실제 파일 앞부분이 '%PDF-'인지 확인한다.
    """
    source.seek(0)
    head = source.read(len(PDF_MAGIC))
    if not head:
        raise BadRequestError("EMPTY_FILE", "Uploaded file is empty.")
    if head != PDF_MAGIC:
        raise UnsupportedMediaTypeError("UNSUPPORTED_MEDIA_TYPE", "Only PDF files are allowed.")

    hasher = hashlib.sha256(head)
    size = len(head)
    while chunk := source.read(_READ_CHUNK):
        size += len(chunk)
        if size > max_bytes:
            raise PayloadTooLargeError(
                "FILE_TOO_LARGE",
                "Uploaded file exceeds the size limit.",
                {"max_bytes": max_bytes},
            )
        hasher.update(chunk)
    source.seek(0)
    return FileInspection(size_bytes=size, sha256=hasher.hexdigest())


def _find_active_by_sha256(db: Session, sha256: str) -> Document | None:
    return db.scalar(
        select(Document).where(Document.sha256 == sha256, Document.deleted_at.is_(None))
    )


def _duplicate_error(existing: Document) -> ConflictError:
    return ConflictError(
        "DOCUMENT_ALREADY_EXISTS",
        "The same file has already been uploaded.",
        {"existing_document_id": str(existing.id)},
    )


def upload_document(
    db: Session,
    storage: FileStorage,
    *,
    filename: str | None,
    source: BinaryIO,
    max_bytes: int,
) -> Document:
    inspection = inspect_pdf(source, max_bytes)

    # 빠른 경로: 이미 있으면 파일을 저장하기 전에 거절한다.
    if existing := _find_active_by_sha256(db, inspection.sha256):
        raise _duplicate_error(existing)

    document_id = uuid.uuid4()
    storage_key = f"{document_id}.pdf"
    document = Document(
        id=document_id,
        original_filename=sanitize_filename(filename),
        content_type=PDF_CONTENT_TYPE,
        size_bytes=inspection.size_bytes,
        sha256=inspection.sha256,
        storage_key=storage_key,
        status=DocumentStatus.UPLOADED,
    )

    # 순서: 파일 저장 → DB 커밋. 커밋이 실패하면 파일을 지운다.
    # 반대 순서면 'DB에는 있는데 파일이 없는' 문서가 생길 수 있고, 그쪽이 더 나쁘다.
    # (커밋 직전 프로세스가 죽으면 고아 파일이 남을 수 있음 → 정리 스크립트로 보완)
    storage.save(storage_key, source)
    try:
        db.add(document)
        audit_service.record_event(
            db,
            action=AuditAction.DOCUMENT_UPLOADED,
            entity_type=EntityType.DOCUMENT,
            entity_id=document_id,
            document_id=document_id,
            changes={"size_bytes": inspection.size_bytes},
        )
        db.commit()
    except IntegrityError:
        # 동시 업로드 경쟁: 위의 SELECT를 둘 다 통과했더라도 부분 유니크 인덱스가 하나만 통과시킨다.
        db.rollback()
        storage.delete(storage_key)
        if existing := _find_active_by_sha256(db, inspection.sha256):
            raise _duplicate_error(existing) from None
        raise
    except BaseException:
        db.rollback()
        storage.delete(storage_key)
        raise

    logger.info(
        "document uploaded",
        extra={"document_id": str(document_id), "size_bytes": inspection.size_bytes},
    )
    return document


def get_document(db: Session, document_id: uuid.UUID, *, for_update: bool = False) -> Document:
    stmt = select(Document).where(Document.id == document_id, Document.deleted_at.is_(None))
    if for_update:
        stmt = stmt.with_for_update()
    document = db.scalar(stmt)
    if document is None:
        raise NotFoundError("DOCUMENT_NOT_FOUND", "Document not found.")
    return document


def list_documents(
    db: Session, *, status: DocumentStatus | None, limit: int, offset: int
) -> tuple[list[Document], int]:
    conditions = [Document.deleted_at.is_(None)]
    if status is not None:
        conditions.append(Document.status == status)

    total = db.scalar(select(func.count()).select_from(Document).where(*conditions)) or 0
    documents = db.scalars(
        select(Document)
        .where(*conditions)
        .order_by(Document.created_at.desc(), Document.id)
        .limit(limit)
        .offset(offset)
    ).all()
    return list(documents), total


def delete_document(db: Session, storage: FileStorage, document_id: uuid.UUID) -> None:
    # FOR UPDATE: 삭제와 '분석 시작'이 동시에 들어와도 한쪽이 끝날 때까지 기다리게 한다.
    document = get_document(db, document_id, for_update=True)
    if document.status == DocumentStatus.PROCESSING:
        raise ConflictError(
            "DOCUMENT_BUSY", "Document cannot be deleted while it is being analyzed."
        )

    document.deleted_at = datetime.now(UTC)
    # M2/M3: document_pages, document_chunks 삭제가 같은 트랜잭션에 추가된다.
    audit_service.record_event(
        db,
        action=AuditAction.DOCUMENT_DELETED,
        entity_type=EntityType.DOCUMENT,
        entity_id=document.id,
        document_id=document.id,
    )
    db.commit()

    # 파일 삭제는 커밋 이후. 실패해도 문서는 이미 비노출 상태이므로 요청은 성공으로 처리하고
    # 고아 파일은 정리 스크립트가 처리한다.
    try:
        storage.delete(document.storage_key)
    except OSError:
        logger.warning(
            "failed to delete stored file", extra={"document_id": str(document.id)}, exc_info=True
        )
