import uuid
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.deps import get_llm_client
from app.core.config import Settings
from app.domain.analysis import AnalysisStatus
from app.domain.document_status import DocumentStatus
from app.llm.base import LLMUnavailableError
from app.llm.fake import FakeLLMClient
from app.models.audit_event import AuditEvent
from app.models.document import Document
from app.models.document_analysis import DocumentAnalysis
from app.models.document_page import DocumentPage
from app.models.llm_call import LlmCall
from app.services import analysis_service
from app.storage.file_storage import LocalFileStorage
from app.workers.analysis_runner import AnalysisRunner
from tests.factories import extraction_json, make_image_only_pdf, make_korean_pdf
from tests.fixtures.sample_contract import SAMPLE_CONTRACT_PAGES

DOCS = "/api/v1/documents"


def upload_contract(client: TestClient, pages: list[str] | None = None) -> str:
    data = make_korean_pdf(pages or SAMPLE_CONTRACT_PAGES)
    response = client.post(DOCS, files={"file": ("contract.pdf", data, "application/pdf")})
    assert response.status_code == 201, response.text
    return str(response.json()["id"])


def start(client: TestClient, document_id: str, **body: Any) -> Any:
    return client.post(f"{DOCS}/{document_id}/analyses", json=body or None)


def count(db: Session, model: type, **filters: Any) -> int:
    stmt = select(func.count()).select_from(model).filter_by(**filters)
    return db.scalar(stmt) or 0


# ---------- 정상 흐름 ----------


def test_analysis_runs_in_background_and_returns_verified_result(
    client: TestClient, db_session: Session, fake_llm: FakeLLMClient
) -> None:
    document_id = upload_contract(client)

    response = start(client, document_id)

    assert response.status_code == 202
    body = response.json()
    assert body["status"] == "QUEUED"
    assert response.headers["Location"] == f"/api/v1/analyses/{body['id']}"

    # TestClient는 백그라운드 작업이 끝난 뒤 반환하므로 바로 결과를 조회할 수 있다.
    analysis = client.get(f"/api/v1/analyses/{body['id']}").json()
    assert analysis["status"] == "SUCCEEDED"
    assert analysis["error"] is None
    assert analysis["llm_model"] == fake_llm.model
    assert analysis["disclaimer"]

    result = analysis["result"]
    assert result["end_date"] == {
        "status": "FOUND",
        "value": "2026-12-31",
        "evidence": [{"page": 1, "quote": "2026년 12월 31일까지로 한다", "verified": True}],
        "verification": "VERIFIED",
    }
    assert result["contract_amount"]["value"] == {"amount": "36000000", "currency": "KRW"}
    assert result["review_items"][0]["item_id"] == "r1"
    assert result["document_stats"]["page_count"] == 3
    assert result["warnings"] == []

    document = client.get(f"{DOCS}/{document_id}").json()
    assert document["status"] == "COMPLETED"
    assert document["page_count"] == 3


def test_successful_analysis_persists_pages_calls_and_audit(
    client: TestClient, db_session: Session
) -> None:
    document_id = upload_contract(client)
    analysis_id = start(client, document_id).json()["id"]
    doc_uuid = uuid.UUID(document_id)

    pages = db_session.scalars(
        select(DocumentPage)
        .where(DocumentPage.document_id == doc_uuid)
        .order_by(DocumentPage.page_no)
    ).all()
    assert [p.page_no for p in pages] == [1, 2, 3]
    assert "제2조(계약기간)" in pages[0].text

    calls = db_session.scalars(
        select(LlmCall).where(LlmCall.analysis_id == uuid.UUID(analysis_id))
    ).all()
    assert [(c.purpose, c.status, c.attempt) for c in calls] == [("FIELD_EXTRACTION", "SUCCESS", 1)]

    actions = db_session.scalars(
        select(AuditEvent.action).where(AuditEvent.document_id == doc_uuid).order_by(AuditEvent.id)
    ).all()
    assert actions == [
        "DOCUMENT_UPLOADED",
        "ANALYSIS_REQUESTED",
        "ANALYSIS_STARTED",
        "ANALYSIS_SUCCEEDED",
    ]


# ---------- 중복 실행 방지 ----------


def test_repeated_request_reuses_succeeded_analysis(
    client: TestClient, db_session: Session, fake_llm: FakeLLMClient
) -> None:
    document_id = upload_contract(client)
    first = start(client, document_id).json()

    response = start(client, document_id)

    assert response.status_code == 200
    assert response.json()["id"] == first["id"]
    assert len(fake_llm.calls) == 1  # LLM을 다시 호출하지 않았다


def test_force_creates_new_analysis_and_keeps_history(
    client: TestClient, fake_llm: FakeLLMClient
) -> None:
    document_id = upload_contract(client)
    first = start(client, document_id).json()

    response = start(client, document_id, force=True)

    assert response.status_code == 202
    assert response.json()["id"] != first["id"]
    assert len(fake_llm.calls) == 2
    history = client.get(f"{DOCS}/{document_id}/analyses").json()
    assert history["total"] == 2
    assert history["items"][0]["id"] == response.json()["id"]  # 최신순
    latest = client.get(f"{DOCS}/{document_id}/analyses/latest").json()
    assert latest["id"] == response.json()["id"]


def test_request_while_in_progress_returns_409(client: TestClient, db_session: Session) -> None:
    document_id = upload_contract(client)
    queued, _ = analysis_service.request_analysis(
        db_session, uuid.UUID(document_id), force=False, llm_model="fake-model"
    )

    response = start(client, document_id)

    assert response.status_code == 409
    error = response.json()["error"]
    assert error["code"] == "ANALYSIS_IN_PROGRESS"
    assert error["details"] == {"analysis_id": str(queued.id)}


def test_database_allows_only_one_in_progress_analysis_per_document(
    client: TestClient, db_session: Session
) -> None:
    document_id = uuid.UUID(upload_contract(client))

    for _ in range(2):
        db_session.add(
            DocumentAnalysis(
                document_id=document_id,
                status=AnalysisStatus.QUEUED,
                pipeline_version="v",
                llm_model="m",
                prompt_version="p",
            )
        )
    with pytest.raises(IntegrityError):
        db_session.flush()
    db_session.rollback()


def test_runner_ignores_analysis_that_is_not_queued(
    client: TestClient,
    db_session: Session,
    session_factory: Callable[[], Session],
    storage: LocalFileStorage,
    settings: Settings,
) -> None:
    document_id = upload_contract(client)
    analysis_id = uuid.UUID(start(client, document_id).json()["id"])
    llm = FakeLLMClient([])  # 호출되면 AssertionError

    AnalysisRunner(session_factory, storage, llm, settings).run(analysis_id)

    assert llm.calls == []


# ---------- 실패 처리 ----------


def test_scanned_pdf_fails_without_calling_llm(
    client: TestClient, db_session: Session, fake_llm: FakeLLMClient
) -> None:
    response = client.post(
        DOCS, files={"file": ("scan.pdf", make_image_only_pdf(2), "application/pdf")}
    )
    document_id = response.json()["id"]

    analysis_id = start(client, document_id).json()["id"]

    analysis = client.get(f"/api/v1/analyses/{analysis_id}").json()
    assert analysis["status"] == "FAILED"
    assert analysis["stage"] == "EXTRACTING"
    assert analysis["error"]["code"] == "NO_TEXT_LAYER"
    assert analysis["result"] is None
    assert fake_llm.calls == []

    document = client.get(f"{DOCS}/{document_id}").json()
    assert document["status"] == "FAILED"
    assert document["error_code"] == "NO_TEXT_LAYER"
    # 실패했더라도 추출 결과(빈 페이지)는 추적용으로 남는다
    assert count(db_session, DocumentPage, document_id=uuid.UUID(document_id)) == 2


def test_llm_outage_fails_analysis_and_is_logged(
    client: TestClient, db_session: Session, fake_llm: FakeLLMClient
) -> None:
    fake_llm._responses = [LLMUnavailableError("timeout")]
    document_id = upload_contract(client)

    analysis_id = start(client, document_id).json()["id"]

    analysis = client.get(f"/api/v1/analyses/{analysis_id}").json()
    assert analysis["status"] == "FAILED"
    assert analysis["stage"] == "FIELD_EXTRACTION"
    assert analysis["error"]["code"] == "LLM_UNAVAILABLE"
    calls = db_session.scalars(
        select(LlmCall).where(LlmCall.analysis_id == uuid.UUID(analysis_id))
    ).all()
    assert [(c.status, c.error_code) for c in calls] == [("ERROR", "LLM_UNAVAILABLE")]
    actions = db_session.scalars(
        select(AuditEvent.action).where(AuditEvent.entity_id == uuid.UUID(analysis_id))
    ).all()
    assert "ANALYSIS_FAILED" in actions


def test_invalid_llm_output_twice_fails_analysis(
    client: TestClient, db_session: Session, fake_llm: FakeLLMClient
) -> None:
    fake_llm._responses = ["{oops", '{"contract_title": null}']
    document_id = upload_contract(client)

    analysis_id = start(client, document_id).json()["id"]

    analysis = client.get(f"/api/v1/analyses/{analysis_id}").json()
    assert analysis["error"]["code"] == "LLM_INVALID_OUTPUT"
    statuses = db_session.scalars(
        select(LlmCall.status)
        .where(LlmCall.analysis_id == uuid.UUID(analysis_id))
        .order_by(LlmCall.attempt)
    ).all()
    assert statuses == ["INVALID_OUTPUT", "INVALID_OUTPUT"]


def test_failed_document_can_be_retried(client: TestClient, fake_llm: FakeLLMClient) -> None:
    fake_llm._responses = [LLMUnavailableError("timeout"), extraction_json()]
    document_id = upload_contract(client)
    failed = start(client, document_id).json()

    retry = start(client, document_id)

    assert retry.status_code == 202
    assert retry.json()["id"] != failed["id"]
    assert client.get(f"/api/v1/analyses/{retry.json()['id']}").json()["status"] == "SUCCEEDED"
    assert client.get(f"{DOCS}/{document_id}").json()["status"] == "COMPLETED"


def test_missing_llm_configuration_returns_503(app: FastAPI, client: TestClient) -> None:
    del app.dependency_overrides[get_llm_client]  # 실제 의존성 + OPENAI_API_KEY 없음
    document_id = upload_contract(client)

    response = start(client, document_id)

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "LLM_NOT_CONFIGURED"
    assert client.get(f"{DOCS}/{document_id}").json()["status"] == "UPLOADED"


# ---------- 조회·삭제 ----------


def test_unknown_analysis_returns_404(client: TestClient) -> None:
    response = client.get(f"/api/v1/analyses/{uuid.uuid4()}")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "ANALYSIS_NOT_FOUND"


def test_latest_without_analysis_returns_404(client: TestClient) -> None:
    document_id = upload_contract(client)
    assert client.get(f"{DOCS}/{document_id}/analyses/latest").status_code == 404


def test_deleting_document_removes_page_text_and_hides_analyses(
    client: TestClient, db_session: Session
) -> None:
    document_id = upload_contract(client)
    analysis_id = start(client, document_id).json()["id"]

    assert client.delete(f"{DOCS}/{document_id}").status_code == 204

    assert count(db_session, DocumentPage, document_id=uuid.UUID(document_id)) == 0
    assert client.get(f"/api/v1/analyses/{analysis_id}").status_code == 404
    assert client.get(f"{DOCS}/{document_id}/analyses").status_code == 404


# ---------- 중단된 작업 정리 ----------


def test_stale_running_analysis_is_marked_interrupted(
    client: TestClient, db_session: Session
) -> None:
    document_id = uuid.UUID(upload_contract(client))
    analysis, _ = analysis_service.request_analysis(
        db_session, document_id, force=False, llm_model="fake-model"
    )
    analysis.status = AnalysisStatus.RUNNING
    analysis.heartbeat_at = datetime.now(UTC) - timedelta(hours=1)
    db_session.commit()

    recovered = analysis_service.fail_stale_analyses(db_session, stale_after=timedelta(minutes=15))

    assert recovered == 1
    db_session.refresh(analysis)
    assert analysis.status == AnalysisStatus.FAILED
    assert analysis.error_code == "INTERRUPTED"
    document = db_session.get(Document, document_id)
    assert document is not None
    db_session.refresh(document)
    assert document.status == DocumentStatus.FAILED


def test_recent_running_analysis_is_left_alone(client: TestClient, db_session: Session) -> None:
    document_id = uuid.UUID(upload_contract(client))
    analysis_service.request_analysis(db_session, document_id, force=False, llm_model="fake-model")

    assert analysis_service.fail_stale_analyses(db_session, stale_after=timedelta(minutes=15)) == 0
