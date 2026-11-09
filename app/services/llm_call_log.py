import uuid

from sqlalchemy.orm import Session

from app.llm.structured import LLMCallRecord
from app.models.llm_call import LlmCall


def record_llm_call(
    db: Session,
    *,
    purpose: str,
    provider: str,
    record: LLMCallRecord,
    prompt_version: str | None = None,
    analysis_id: uuid.UUID | None = None,
    document_id: uuid.UUID | None = None,
) -> None:
    """호출 메타데이터(지연·토큰·상태)만 세션에 추가한다. 커밋은 호출한 쪽이 한다."""
    db.add(
        LlmCall(
            purpose=purpose,
            provider=provider,
            model=record.model,
            prompt_version=prompt_version,
            analysis_id=analysis_id,
            document_id=document_id,
            attempt=record.attempt,
            status=record.status,
            latency_ms=record.latency_ms,
            input_tokens=record.input_tokens,
            output_tokens=record.output_tokens,
            error_code=record.error_code,
        )
    )
