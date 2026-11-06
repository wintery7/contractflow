"""분석 실행 오케스트레이션 (BackgroundTasks 진입점).

요청 처리용 세션과 별개로 자기 세션을 연다. 단계가 바뀔 때마다 커밋해
클라이언트가 GET /analyses/{id}로 진행 상황(stage)을 볼 수 있게 한다.

실행기를 별도 워커 프로세스로 옮기더라도(SKIP LOCKED 폴링) 이 클래스는 그대로 재사용된다.
상태의 정본이 DB에 있기 때문이다.
"""

import logging
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import delete
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.logging import request_id_var
from app.domain.analysis import (
    AnalysisErrorCode,
    AnalysisFailure,
    AnalysisStage,
    AnalysisStatus,
    ensure_analysis_transition,
)
from app.domain.audit import ActorType, AuditAction, AuditOutcome, EntityType
from app.domain.document_status import DocumentStatus, ensure_transition
from app.extraction.extractor import LLMCallRecord, extract_contract_fields
from app.extraction.prompts import PROMPT_VERSION
from app.extraction.schemas import DocumentStats
from app.extraction.verifier import build_result
from app.llm.base import LLMClient
from app.models.document import Document
from app.models.document_analysis import DocumentAnalysis
from app.models.document_page import DocumentPage
from app.models.llm_call import LlmCall
from app.pipeline.pdf_extractor import PageText, extract_pages
from app.pipeline.text_cleaner import clean_pages, compute_stats, ensure_analyzable
from app.services import audit_service
from app.storage.file_storage import FileStorage

logger = logging.getLogger(__name__)


@dataclass
class AnalysisRunner:
    session_factory: Callable[[], Session]
    storage: FileStorage
    llm: LLMClient
    settings: Settings

    def run(self, analysis_id: uuid.UUID, request_id: str | None = None) -> None:
        # 백그라운드 작업에도 요청 ID를 이어 붙여 로그를 한 흐름으로 추적한다.
        token = request_id_var.set(request_id)
        started = time.perf_counter()
        try:
            with self.session_factory() as db:
                try:
                    self._run(db, analysis_id)
                except Exception:
                    logger.exception("analysis crashed", extra={"analysis_id": str(analysis_id)})
                    db.rollback()
                    self._fail_by_id(db, analysis_id, AnalysisErrorCode.INTERNAL_ERROR)
        finally:
            logger.info(
                "analysis finished",
                extra={
                    "analysis_id": str(analysis_id),
                    "duration_ms": round((time.perf_counter() - started) * 1000),
                },
            )
            request_id_var.reset(token)

    # ---------- 실행 단계 ----------

    def _run(self, db: Session, analysis_id: uuid.UUID) -> None:
        analysis = db.get(DocumentAnalysis, analysis_id, with_for_update=True)
        if analysis is None or analysis.status != AnalysisStatus.QUEUED:
            # 이미 다른 실행기가 가져갔거나 끝난 작업: 아무것도 하지 않는다 (중복 실행 방지)
            logger.warning(
                "analysis is not queued; skipping", extra={"analysis_id": str(analysis_id)}
            )
            return
        document = db.get(Document, analysis.document_id)
        assert document is not None  # FK로 보장

        analysis.status = ensure_analysis_transition(
            AnalysisStatus(analysis.status), AnalysisStatus.RUNNING
        )
        analysis.started_at = datetime.now(UTC)
        self._enter_stage(analysis, AnalysisStage.EXTRACTING)
        self._audit(db, analysis, AuditAction.ANALYSIS_STARTED)
        db.commit()

        try:
            pages, stats = self._extract_text(db, document)
            self._enter_stage(analysis, AnalysisStage.FIELD_EXTRACTION)
            db.commit()

            extraction = extract_contract_fields(
                pages, self.llm, on_call=lambda record: self._record_call(db, analysis, record)
            )
            result = build_result(extraction, pages, stats)
        except AnalysisFailure as failure:
            self._fail(db, analysis, document, failure.code, failure.message)
            return

        analysis.result = result.model_dump(mode="json")
        analysis.status = ensure_analysis_transition(
            AnalysisStatus(analysis.status), AnalysisStatus.SUCCEEDED
        )
        analysis.stage = None
        analysis.finished_at = datetime.now(UTC)
        document.status = ensure_transition(
            DocumentStatus(document.status), DocumentStatus.COMPLETED
        )
        document.error_code = None
        document.error_message = None
        self._audit(
            db, analysis, AuditAction.ANALYSIS_SUCCEEDED, changes={"warnings": len(result.warnings)}
        )
        db.commit()

    def _extract_text(
        self, db: Session, document: Document
    ) -> tuple[list[PageText], DocumentStats]:
        if not self.storage.exists(document.storage_key):
            raise AnalysisFailure(AnalysisErrorCode.FILE_MISSING, "The stored PDF file is missing.")

        pages = clean_pages(
            extract_pages(
                self.storage.path(document.storage_key), max_pages=self.settings.max_pages
            )
        )
        stats = compute_stats(pages)

        # 추출 결과는 실패(텍스트 없음 등)하더라도 남겨 둔다 → 어떤 페이지가 비었는지 추적 가능
        db.execute(delete(DocumentPage).where(DocumentPage.document_id == document.id))
        db.add_all(
            DocumentPage(
                document_id=document.id,
                page_no=page.page_no,
                text=page.text,
                char_count=len("".join(page.text.split())),
            )
            for page in pages
        )
        document.page_count = stats.page_count
        db.commit()

        ensure_analyzable(
            stats,
            min_chars=self.settings.min_text_chars,
            max_chars=self.settings.max_analysis_chars,
        )
        return pages, DocumentStats(
            page_count=stats.page_count, char_count=stats.char_count, empty_pages=stats.empty_pages
        )

    # ---------- 보조 ----------

    @staticmethod
    def _enter_stage(analysis: DocumentAnalysis, stage: AnalysisStage) -> None:
        analysis.stage = stage
        analysis.heartbeat_at = datetime.now(UTC)

    def _record_call(self, db: Session, analysis: DocumentAnalysis, record: LLMCallRecord) -> None:
        db.add(
            LlmCall(
                purpose="FIELD_EXTRACTION",
                provider=self.llm.provider,
                model=record.model,
                prompt_version=PROMPT_VERSION,
                analysis_id=analysis.id,
                document_id=analysis.document_id,
                attempt=record.attempt,
                status=record.status,
                latency_ms=record.latency_ms,
                input_tokens=record.input_tokens,
                output_tokens=record.output_tokens,
                error_code=record.error_code,
            )
        )
        analysis.heartbeat_at = datetime.now(UTC)

    @staticmethod
    def _audit(
        db: Session,
        analysis: DocumentAnalysis,
        action: AuditAction,
        *,
        outcome: AuditOutcome = AuditOutcome.SUCCESS,
        changes: dict[str, object] | None = None,
    ) -> None:
        audit_service.record_event(
            db,
            action=action,
            entity_type=EntityType.ANALYSIS,
            entity_id=analysis.id,
            document_id=analysis.document_id,
            actor_type=ActorType.SYSTEM,
            outcome=outcome,
            changes=changes,
        )

    def _fail(
        self,
        db: Session,
        analysis: DocumentAnalysis,
        document: Document,
        code: AnalysisErrorCode,
        message: str,
    ) -> None:
        analysis.status = ensure_analysis_transition(
            AnalysisStatus(analysis.status), AnalysisStatus.FAILED
        )
        analysis.error_code = code
        analysis.error_message = message[:500]
        analysis.finished_at = datetime.now(UTC)
        if document.status == DocumentStatus.PROCESSING:
            document.status = DocumentStatus.FAILED
        document.error_code = code
        document.error_message = message[:500]
        self._audit(
            db,
            analysis,
            AuditAction.ANALYSIS_FAILED,
            outcome=AuditOutcome.FAILURE,
            changes={"error_code": code, "stage": analysis.stage},
        )
        db.commit()
        logger.warning(
            "analysis failed",
            extra={"analysis_id": str(analysis.id), "error_code": code, "stage": analysis.stage},
        )

    def _fail_by_id(self, db: Session, analysis_id: uuid.UUID, code: AnalysisErrorCode) -> None:
        analysis = db.get(DocumentAnalysis, analysis_id)
        if analysis is None or analysis.status not in (
            AnalysisStatus.QUEUED,
            AnalysisStatus.RUNNING,
        ):
            return
        document = db.get(Document, analysis.document_id)
        assert document is not None
        self._fail(db, analysis, document, code, "Unexpected error during analysis.")
