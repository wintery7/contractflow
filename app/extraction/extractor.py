"""LLM 호출 → 형식 검증 → (실패 시 1회 교정 요청) → 구조화 추출 결과."""

import time
from collections.abc import Callable
from dataclasses import dataclass

from pydantic import ValidationError

from app.domain.analysis import AnalysisErrorCode, AnalysisFailure
from app.extraction.prompts import CORRECTION_PROMPT, SYSTEM_PROMPT, build_document_message
from app.extraction.schemas import ContractExtraction
from app.llm.base import ChatMessage, LLMClient, LLMRequestRejectedError, LLMUnavailableError
from app.llm.strict_schema import to_strict_json_schema
from app.pipeline.pdf_extractor import PageText

MAX_ATTEMPTS = 2
_MAX_REPORTED_ERRORS = 10
_SCHEMA = to_strict_json_schema(ContractExtraction)


@dataclass(frozen=True)
class LLMCallRecord:
    """llm_calls 테이블에 남길 호출 메타데이터. 프롬프트·응답 본문은 담지 않는다."""

    model: str
    attempt: int
    status: str  # SUCCESS | ERROR | INVALID_OUTPUT
    latency_ms: int
    input_tokens: int | None = None
    output_tokens: int | None = None
    error_code: str | None = None


OnCall = Callable[[LLMCallRecord], None]


def _format_errors(exc: ValidationError) -> str:
    # 사용자가 보낸 값('input')은 빼고 위치와 메시지만 전달한다.
    lines = [
        f"- {'.'.join(str(p) for p in err['loc']) or '(root)'}: {err['msg']}"
        for err in exc.errors()[:_MAX_REPORTED_ERRORS]
    ]
    return "\n".join(lines)


def extract_contract_fields(
    pages: list[PageText], llm: LLMClient, on_call: OnCall
) -> ContractExtraction:
    messages = [ChatMessage("user", build_document_message(pages))]

    for attempt in range(1, MAX_ATTEMPTS + 1):
        started = time.perf_counter()
        try:
            result = llm.complete_json(
                system=SYSTEM_PROMPT,
                messages=messages,
                schema_name="contract_extraction",
                json_schema=_SCHEMA,
            )
        except (LLMUnavailableError, LLMRequestRejectedError) as exc:
            code = (
                AnalysisErrorCode.LLM_UNAVAILABLE
                if isinstance(exc, LLMUnavailableError)
                else AnalysisErrorCode.LLM_REQUEST_REJECTED
            )
            on_call(
                LLMCallRecord(
                    model=llm.model,
                    attempt=attempt,
                    status="ERROR",
                    latency_ms=_elapsed_ms(started),
                    error_code=code,
                )
            )
            raise AnalysisFailure(code, "The language model request failed.") from exc

        latency_ms = _elapsed_ms(started)
        try:
            extraction = ContractExtraction.model_validate_json(result.content)
        except ValidationError as exc:
            on_call(
                LLMCallRecord(
                    model=result.model,
                    attempt=attempt,
                    status="INVALID_OUTPUT",
                    latency_ms=latency_ms,
                    input_tokens=result.input_tokens,
                    output_tokens=result.output_tokens,
                    error_code=AnalysisErrorCode.LLM_INVALID_OUTPUT,
                )
            )
            # 대화에 직전 응답과 오류를 덧붙여 교정을 요청한다.
            messages += [
                ChatMessage("assistant", result.content),
                ChatMessage("user", CORRECTION_PROMPT.format(errors=_format_errors(exc))),
            ]
            continue

        on_call(
            LLMCallRecord(
                model=result.model,
                attempt=attempt,
                status="SUCCESS",
                latency_ms=latency_ms,
                input_tokens=result.input_tokens,
                output_tokens=result.output_tokens,
            )
        )
        return extraction

    raise AnalysisFailure(
        AnalysisErrorCode.LLM_INVALID_OUTPUT,
        f"The language model returned invalid output {MAX_ATTEMPTS} times.",
    )


def _elapsed_ms(started: float) -> int:
    return round((time.perf_counter() - started) * 1000)
