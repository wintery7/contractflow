import uuid
from typing import Annotated, Any

from fastapi import APIRouter, File, Query, Response, UploadFile, status

from app.api.deps import DbSession, SettingsDep, StorageDep
from app.domain.document_status import DocumentStatus
from app.schemas.audit import AuditEventResponse
from app.schemas.common import ErrorResponse, Page
from app.schemas.document import DocumentResponse
from app.services import audit_service, document_service

router = APIRouter(prefix="/documents", tags=["documents"])


def _errors(*codes: int) -> dict[int | str, dict[str, Any]]:
    return {code: {"model": ErrorResponse} for code in codes}


Limit = Annotated[int, Query(ge=1, le=100)]
Offset = Annotated[int, Query(ge=0)]


@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    response_model=DocumentResponse,
    responses=_errors(400, 409, 413, 415),
    summary="계약서 PDF 업로드",
)
def upload_document(
    response: Response,
    db: DbSession,
    storage: StorageDep,
    settings: SettingsDep,
    file: Annotated[UploadFile, File(description="PDF 파일")],
) -> DocumentResponse:
    document = document_service.upload_document(
        db,
        storage,
        filename=file.filename,
        source=file.file,
        max_bytes=settings.max_upload_bytes,
    )
    response.headers["Location"] = f"/api/v1/documents/{document.id}"
    return DocumentResponse.model_validate(document)


@router.get("", response_model=Page[DocumentResponse], summary="문서 목록")
def list_documents(
    db: DbSession,
    status_filter: Annotated[DocumentStatus | None, Query(alias="status")] = None,
    limit: Limit = 20,
    offset: Offset = 0,
) -> Page[DocumentResponse]:
    documents, total = document_service.list_documents(
        db, status=status_filter, limit=limit, offset=offset
    )
    return Page[DocumentResponse](
        items=[DocumentResponse.model_validate(d) for d in documents],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get(
    "/{document_id}",
    response_model=DocumentResponse,
    responses=_errors(404),
    summary="문서 상세",
)
def get_document(document_id: uuid.UUID, db: DbSession) -> DocumentResponse:
    return DocumentResponse.model_validate(document_service.get_document(db, document_id))


@router.delete(
    "/{document_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    responses=_errors(404, 409),
    summary="문서 삭제 (소프트 삭제 + 원본 파일 제거)",
)
def delete_document(document_id: uuid.UUID, db: DbSession, storage: StorageDep) -> Response:
    document_service.delete_document(db, storage, document_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get(
    "/{document_id}/history",
    response_model=Page[AuditEventResponse],
    responses=_errors(404),
    summary="문서 처리 이력",
)
def get_document_history(
    document_id: uuid.UUID, db: DbSession, limit: Limit = 20, offset: Offset = 0
) -> Page[AuditEventResponse]:
    document_service.get_document(db, document_id)  # 삭제/부재 문서는 404
    events, total = audit_service.list_document_events(db, document_id, limit=limit, offset=offset)
    return Page[AuditEventResponse](
        items=[AuditEventResponse.model_validate(e) for e in events],
        total=total,
        limit=limit,
        offset=offset,
    )
