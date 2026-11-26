import uuid
from typing import Annotated

from fastapi import APIRouter, Depends

from app.api.deps import DbSession, SettingsDep, get_embedder, get_llm_client
from app.llm.base import LLMClient
from app.llm.embeddings import Embedder
from app.schemas.common import ErrorResponse
from app.schemas.question import QuestionRequest, QuestionResponse
from app.services import qa_service

router = APIRouter(tags=["questions"])


@router.post(
    "/documents/{document_id}/questions",
    response_model=QuestionResponse,
    responses={code: {"model": ErrorResponse} for code in (404, 409, 503)},
    summary="계약서 질의응답 (근거 청크·페이지 포함)",
)
def ask_question(
    document_id: uuid.UUID,
    body: QuestionRequest,
    db: DbSession,
    settings: SettingsDep,
    embedder: Annotated[Embedder, Depends(get_embedder)],
    llm: Annotated[LLMClient, Depends(get_llm_client)],
) -> QuestionResponse:
    result = qa_service.answer_question(
        db,
        document_id,
        body.question,
        top_k=body.top_k or settings.qa_top_k,
        min_score=settings.qa_min_score,
        embedder=embedder,
        llm=llm,
    )
    return QuestionResponse.from_result(body.question, result)
