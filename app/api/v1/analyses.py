import uuid
from typing import Annotated, Any

from fastapi import APIRouter, BackgroundTasks, Depends, Query, Response, status

from app.api.deps import DbSession, get_analysis_runner
from app.core.logging import request_id_var
from app.schemas.analysis import AnalysisRequest, AnalysisResponse, AnalysisSummary
from app.schemas.common import ErrorResponse, Page
from app.services import analysis_service
from app.workers.analysis_runner import AnalysisRunner

router = APIRouter(tags=["analyses"])


def _errors(*codes: int) -> dict[int | str, dict[str, Any]]:
    return {code: {"model": ErrorResponse} for code in codes}


@router.post(
    "/documents/{document_id}/analyses",
    response_model=AnalysisResponse,
    status_code=status.HTTP_202_ACCEPTED,
    responses={
        200: {"model": AnalysisResponse, "description": "같은 조건의 기존 성공 결과 재사용"},
        **_errors(404, 409, 503),
    },
    summary="분석 시작 (비동기)",
)
def start_analysis(
    document_id: uuid.UUID,
    response: Response,
    background_tasks: BackgroundTasks,
    db: DbSession,
    runner: Annotated[AnalysisRunner, Depends(get_analysis_runner)],
    body: AnalysisRequest | None = None,
) -> AnalysisResponse:
    analysis, created = analysis_service.request_analysis(
        db, document_id, force=(body or AnalysisRequest()).force, llm_model=runner.llm.model
    )
    response.headers["Location"] = f"/api/v1/analyses/{analysis.id}"
    if created:
        # 응답을 보낸 뒤 같은 프로세스에서 실행된다. 상태는 GET /analyses/{id}로 확인한다.
        background_tasks.add_task(runner.run, analysis.id, request_id_var.get())
    else:
        response.status_code = status.HTTP_200_OK
    return AnalysisResponse.from_model(analysis)


@router.get(
    "/documents/{document_id}/analyses",
    response_model=Page[AnalysisSummary],
    responses=_errors(404),
    summary="문서의 분석 이력 (최신순)",
)
def list_analyses(
    document_id: uuid.UUID,
    db: DbSession,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> Page[AnalysisSummary]:
    analyses, total = analysis_service.list_analyses(db, document_id, limit=limit, offset=offset)
    return Page[AnalysisSummary](
        items=[AnalysisSummary.from_model(a) for a in analyses],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get(
    "/documents/{document_id}/analyses/latest",
    response_model=AnalysisResponse,
    responses=_errors(404),
    summary="가장 최근 분석",
)
def get_latest_analysis(document_id: uuid.UUID, db: DbSession) -> AnalysisResponse:
    return AnalysisResponse.from_model(analysis_service.get_latest_analysis(db, document_id))


@router.get(
    "/analyses/{analysis_id}",
    response_model=AnalysisResponse,
    responses=_errors(404),
    summary="분석 상태·결과 조회 (폴링)",
)
def get_analysis(analysis_id: uuid.UUID, db: DbSession) -> AnalysisResponse:
    return AnalysisResponse.from_model(analysis_service.get_analysis(db, analysis_id))
