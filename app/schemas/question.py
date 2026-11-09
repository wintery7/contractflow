import uuid

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.analysis import DISCLAIMER
from app.services.qa_service import AnswerStatus, InsufficientReason, QAResult


class QuestionRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    question: str = Field(min_length=1, max_length=500)
    top_k: int | None = Field(default=None, ge=1, le=20, description="기본값은 서버 설정(QA_TOP_K)")


class CitationResponse(BaseModel):
    chunk_id: uuid.UUID
    chunk_index: int
    page_start: int
    page_end: int
    excerpt: str
    score: float = Field(description="코사인 유사도. 관련성 신호일 뿐 답의 정확성을 뜻하지 않는다.")
    cited_by_answer: bool


class RetrievalInfo(BaseModel):
    top_k: int
    max_score: float | None
    min_score_threshold: float


class QuestionResponse(BaseModel):
    question: str
    status: AnswerStatus
    reason: InsufficientReason | None
    answer: str | None
    citations: list[CitationResponse]
    retrieval: RetrievalInfo
    disclaimer: str = DISCLAIMER

    @classmethod
    def from_result(cls, question: str, result: QAResult) -> "QuestionResponse":
        return cls(
            question=question,
            status=result.status,
            reason=result.reason,
            answer=result.answer,
            citations=[
                CitationResponse(
                    chunk_id=c.chunk.chunk_id,
                    chunk_index=c.chunk.chunk_index,
                    page_start=c.chunk.page_start,
                    page_end=c.chunk.page_end,
                    excerpt=c.chunk.content,
                    score=c.chunk.score,
                    cited_by_answer=c.cited_by_answer,
                )
                for c in result.citations
            ],
            retrieval=RetrievalInfo(
                top_k=result.top_k,
                max_score=result.max_score,
                min_score_threshold=result.min_score,
            ),
        )
