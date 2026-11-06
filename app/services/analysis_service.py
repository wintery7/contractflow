"""분석 요청·조회·중단 작업 정리 유스케이스."""

import logging
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.errors import ConflictError, NotFoundError
from app.domain.analysis import (
    IN_PROGRESS_STATUSES,
    PIPELINE_VERSION,
    AnalysisErrorCode,
    AnalysisStatus,
)
from app.domain.audit import ActorType, AuditAction, AuditOutcome, EntityType
from app.domain.document_status import DocumentStatus, ensure_transition
from app.extraction.prompts import PROMPT_VERSION
from app.models.document import Document
from app.models.document_analysis import DocumentAnalysis
from app.services import audit_service, document_service

logger = logging.getLogger(__name__)


def _in_progress_conflict(analysis_id: uuid.UUID) -> ConflictError:
    return ConflictError(
        "ANALYSIS_IN_PROGRESS",
        "An analysis is already running for this document.",
        {"analysis_id": str(analysis_id)},
    )


def request_analysis(
    db: Session, document_id: uuid.UUID, *, force: bool, llm_model: str
) -> tuple[DocumentAnalysis, bool]:
    """분석을 큐에 넣는다. (분석, 새로 만들었는지) 를 반환한다.

    - 진행 중인 분석이 있으면 409
    - 같은 파이프라인·모델·프롬프트로 성공한 분석이 있고 force가 아니면 기존 결과 재사용
      (같은 문서를 반복 분석해 LLM 비용을 낭비하지 않기 위함)
    """
    # 문서 행을 잠가 같은 문서에 대한 동시 요청을 줄 세운다.
    document = document_service.get_document(db, document_id, for_update=True)

    in_progress = db.scalar(
        select(DocumentAnalysis).where(
            DocumentAnalysis.document_id == document_id,
            DocumentAnalysis.status.in_(IN_PROGRESS_STATUSES),
        )
    )
    if in_progress is not None:
        raise _in_progress_conflict(in_progress.id)

    if not force:
        reusable = db.scalar(
            select(DocumentAnalysis)
            .where(
                DocumentAnalysis.document_id == document_id,
                DocumentAnalysis.status == AnalysisStatus.SUCCEEDED,
                DocumentAnalysis.pipeline_version == PIPELINE_VERSION,
                DocumentAnalysis.llm_model == llm_model,
                DocumentAnalysis.prompt_version == PROMPT_VERSION,
            )
            .order_by(DocumentAnalysis.created_at.desc())
            .limit(1)
        )
        if reusable is not None:
            return reusable, False

    document.status = ensure_transition(DocumentStatus(document.status), DocumentStatus.PROCESSING)
    analysis = DocumentAnalysis(
        id=uuid.uuid4(),
        document_id=document_id,
        status=AnalysisStatus.QUEUED,
        pipeline_version=PIPELINE_VERSION,
        llm_model=llm_model,
        prompt_version=PROMPT_VERSION,
    )
    db.add(analysis)
    audit_service.record_event(
        db,
        action=AuditAction.ANALYSIS_REQUESTED,
        entity_type=EntityType.ANALYSIS,
        entity_id=analysis.id,
        document_id=document_id,
        changes={"force": force, "llm_model": llm_model, "prompt_version": PROMPT_VERSION},
    )
    try:
        db.commit()
    except IntegrityError:
        # 잠금을 우회한 경쟁이 있더라도 부분 유니크 인덱스가 마지막 방어선이 된다.
        db.rollback()
        existing = db.scalar(
            select(DocumentAnalysis.id).where(
                DocumentAnalysis.document_id == document_id,
                DocumentAnalysis.status.in_(IN_PROGRESS_STATUSES),
            )
        )
        if existing is not None:
            raise _in_progress_conflict(existing) from None
        raise
    return analysis, True


def get_analysis(db: Session, analysis_id: uuid.UUID) -> DocumentAnalysis:
    # 삭제된 문서의 분석은 노출하지 않는다.
    analysis = db.scalar(
        select(DocumentAnalysis)
        .join(Document, Document.id == DocumentAnalysis.document_id)
        .where(DocumentAnalysis.id == analysis_id, Document.deleted_at.is_(None))
    )
    if analysis is None:
        raise NotFoundError("ANALYSIS_NOT_FOUND", "Analysis not found.")
    return analysis


def list_analyses(
    db: Session, document_id: uuid.UUID, *, limit: int, offset: int
) -> tuple[list[DocumentAnalysis], int]:
    document_service.get_document(db, document_id)
    condition = DocumentAnalysis.document_id == document_id
    total = db.scalar(select(func.count()).select_from(DocumentAnalysis).where(condition)) or 0
    analyses = db.scalars(
        select(DocumentAnalysis)
        .where(condition)
        .order_by(DocumentAnalysis.created_at.desc(), DocumentAnalysis.id)
        .limit(limit)
        .offset(offset)
    ).all()
    return list(analyses), total


def get_latest_analysis(db: Session, document_id: uuid.UUID) -> DocumentAnalysis:
    analyses, _ = list_analyses(db, document_id, limit=1, offset=0)
    if not analyses:
        raise NotFoundError("ANALYSIS_NOT_FOUND", "This document has not been analyzed yet.")
    return analyses[0]


def fail_stale_analyses(db: Session, *, stale_after: timedelta) -> int:
    """하트비트가 끊긴 QUEUED/RUNNING 분석을 FAILED(INTERRUPTED)로 정리한다.

    BackgroundTasks는 같은 프로세스에서 실행되므로 서버가 재시작되면 실행 중이던 작업이 사라진다.
    자동 재실행은 하지 않는다(중복 LLM 비용, 부분 실패 상태 위험). 사용자가 다시 요청하면 된다.
    """
    cutoff = datetime.now(UTC) - stale_after
    stale = db.scalars(
        select(DocumentAnalysis)
        .where(
            DocumentAnalysis.status.in_(IN_PROGRESS_STATUSES),
            DocumentAnalysis.heartbeat_at < cutoff,
        )
        .with_for_update(skip_locked=True)
    ).all()

    for analysis in stale:
        document = db.get(Document, analysis.document_id)
        analysis.status = AnalysisStatus.FAILED
        analysis.error_code = AnalysisErrorCode.INTERRUPTED
        analysis.error_message = "The analysis was interrupted (server restart or crash)."
        analysis.finished_at = datetime.now(UTC)
        if document is not None and document.status == DocumentStatus.PROCESSING:
            document.status = DocumentStatus.FAILED
            document.error_code = AnalysisErrorCode.INTERRUPTED
        audit_service.record_event(
            db,
            action=AuditAction.ANALYSIS_FAILED,
            entity_type=EntityType.ANALYSIS,
            entity_id=analysis.id,
            document_id=analysis.document_id,
            actor_type=ActorType.SYSTEM,
            outcome=AuditOutcome.FAILURE,
            changes={"error_code": AnalysisErrorCode.INTERRUPTED},
        )
    db.commit()
    if stale:
        logger.warning("marked stale analyses as failed", extra={"count": len(stale)})
    return len(stale)
