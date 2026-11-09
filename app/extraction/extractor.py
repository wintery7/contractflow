"""계약서 구조화 추출: 공통 구조화 출력 흐름을 쓰고, 실패를 분석 오류 코드로 바꾼다."""

from app.domain.analysis import AnalysisErrorCode, AnalysisFailure
from app.extraction.prompts import CORRECTION_PROMPT, SYSTEM_PROMPT, build_document_message
from app.extraction.schemas import ContractExtraction
from app.llm.base import LLMClient, LLMRequestRejectedError, LLMUnavailableError
from app.llm.strict_schema import to_strict_json_schema
from app.llm.structured import (
    MAX_ATTEMPTS,
    LLMCallRecord,
    OnCall,
    StructuredOutputError,
    generate_structured,
)
from app.pipeline.pdf_extractor import PageText

__all__ = ["MAX_ATTEMPTS", "LLMCallRecord", "OnCall", "extract_contract_fields"]

_SCHEMA = to_strict_json_schema(ContractExtraction)


def extract_contract_fields(
    pages: list[PageText], llm: LLMClient, on_call: OnCall
) -> ContractExtraction:
    try:
        return generate_structured(
            llm,
            system=SYSTEM_PROMPT,
            user_message=build_document_message(pages),
            output_model=ContractExtraction,
            json_schema=_SCHEMA,
            schema_name="contract_extraction",
            on_call=on_call,
            correction_prompt=CORRECTION_PROMPT,
        )
    except LLMUnavailableError as exc:
        raise AnalysisFailure(
            AnalysisErrorCode.LLM_UNAVAILABLE, "The language model request failed."
        ) from exc
    except LLMRequestRejectedError as exc:
        raise AnalysisFailure(
            AnalysisErrorCode.LLM_REQUEST_REJECTED, "The language model request failed."
        ) from exc
    except StructuredOutputError as exc:
        raise AnalysisFailure(
            AnalysisErrorCode.LLM_INVALID_OUTPUT,
            f"The language model returned invalid output {MAX_ATTEMPTS} times.",
        ) from exc
