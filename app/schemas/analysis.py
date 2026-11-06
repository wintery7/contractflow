import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from app.domain.analysis import AnalysisStatus
from app.extraction.schemas import AnalysisResult
from app.models.document_analysis import DocumentAnalysis

DISCLAIMER = "본 결과는 법률 자문이 아닌 검토 보조 자료입니다."


class AnalysisRequest(BaseModel):
    force: bool = Field(
        default=False, description="같은 조건의 성공한 분석이 있어도 새로 분석한다 (LLM 비용 발생)"
    )


class AnalysisError(BaseModel):
    code: str
    message: str | None


class AnalysisSummary(BaseModel):
    id: uuid.UUID
    document_id: uuid.UUID
    status: AnalysisStatus
    stage: str | None
    pipeline_version: str
    llm_model: str
    prompt_version: str
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    error: AnalysisError | None

    @classmethod
    def from_model(cls, analysis: DocumentAnalysis) -> "AnalysisSummary":
        return cls(**_summary_fields(analysis))


class AnalysisResponse(AnalysisSummary):
    result: AnalysisResult | None
    disclaimer: str = DISCLAIMER

    @classmethod
    def from_model(cls, analysis: DocumentAnalysis) -> "AnalysisResponse":
        result = AnalysisResult.model_validate(analysis.result) if analysis.result else None
        return cls(**_summary_fields(analysis), result=result)


def _summary_fields(analysis: DocumentAnalysis) -> dict[str, Any]:
    error = (
        AnalysisError(code=analysis.error_code, message=analysis.error_message)
        if analysis.error_code
        else None
    )
    return {
        "id": analysis.id,
        "document_id": analysis.document_id,
        "status": analysis.status,
        "stage": analysis.stage,
        "pipeline_version": analysis.pipeline_version,
        "llm_model": analysis.llm_model,
        "prompt_version": analysis.prompt_version,
        "created_at": analysis.created_at,
        "started_at": analysis.started_at,
        "finished_at": analysis.finished_at,
        "error": error,
    }
