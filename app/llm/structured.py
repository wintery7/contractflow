"""LLM 구조화 출력 공통 흐름: 호출 → Pydantic 검증 → (실패 시 1회 교정 요청).

구조화 추출(분석)과 질의응답이 같은 흐름을 쓴다. 호출마다 LLMCallRecord를 콜백으로 넘겨
호출한 쪽이 llm_calls 테이블에 기록하게 한다. 프롬프트·응답 본문은 기록하지 않는다.
"""

import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, TypeVar

from pydantic import BaseModel, ValidationError

from app.llm.base import ChatMessage, LLMClient, LLMRequestRejectedError, LLMUnavailableError

MAX_ATTEMPTS = 2
_MAX_REPORTED_ERRORS = 10

CORRECTION_PROMPT = """\
직전 응답이 형식 검증을 통과하지 못했습니다. 아래 오류를 고쳐 전체 JSON을 다시 출력하십시오.
입력에 없는 값을 지어내서 오류를 해결하지 마십시오.

오류:
{errors}
"""


@dataclass(frozen=True)
class LLMCallRecord:
    """llm_calls 테이블에 남길 호출 메타데이터."""

    model: str
    attempt: int
    status: str  # SUCCESS | ERROR | INVALID_OUTPUT
    latency_ms: int
    input_tokens: int | None = None
    output_tokens: int | None = None
    error_code: str | None = None


OnCall = Callable[[LLMCallRecord], None]

# Python 3.11이라 PEP 695 제네릭 문법 대신 TypeVar를 쓴다.
T = TypeVar("T", bound=BaseModel)


class StructuredOutputError(Exception):
    """MAX_ATTEMPTS번 모두 형식 검증에 실패했다."""


def error_code_for(exc: Exception) -> str:
    return "LLM_UNAVAILABLE" if isinstance(exc, LLMUnavailableError) else "LLM_REQUEST_REJECTED"


def elapsed_ms(started: float) -> int:
    return round((time.perf_counter() - started) * 1000)


def _format_errors(exc: ValidationError) -> str:
    # 모델이 보낸 값('input')은 빼고 위치와 메시지만 전달한다.
    return "\n".join(
        f"- {'.'.join(str(p) for p in err['loc']) or '(root)'}: {err['msg']}"
        for err in exc.errors()[:_MAX_REPORTED_ERRORS]
    )


def generate_structured(
    llm: LLMClient,
    *,
    system: str,
    user_message: str,
    output_model: type[T],
    json_schema: dict[str, Any],
    schema_name: str,
    on_call: OnCall,
    correction_prompt: str = CORRECTION_PROMPT,
) -> T:
    """LLM 오류(LLMUnavailableError 등)는 기록 후 그대로 올린다. SDK가 이미 재시도했기 때문이다."""
    messages = [ChatMessage("user", user_message)]

    for attempt in range(1, MAX_ATTEMPTS + 1):
        started = time.perf_counter()
        try:
            result = llm.complete_json(
                system=system, messages=messages, schema_name=schema_name, json_schema=json_schema
            )
        except (LLMUnavailableError, LLMRequestRejectedError) as exc:
            on_call(
                LLMCallRecord(
                    model=llm.model,
                    attempt=attempt,
                    status="ERROR",
                    latency_ms=elapsed_ms(started),
                    error_code=error_code_for(exc),
                )
            )
            raise

        latency_ms = elapsed_ms(started)
        try:
            parsed = output_model.model_validate_json(result.content)
        except ValidationError as exc:
            on_call(
                LLMCallRecord(
                    model=result.model,
                    attempt=attempt,
                    status="INVALID_OUTPUT",
                    latency_ms=latency_ms,
                    input_tokens=result.input_tokens,
                    output_tokens=result.output_tokens,
                    error_code="LLM_INVALID_OUTPUT",
                )
            )
            messages += [
                ChatMessage("assistant", result.content),
                ChatMessage("user", correction_prompt.format(errors=_format_errors(exc))),
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
        return parsed

    raise StructuredOutputError(f"invalid output {MAX_ATTEMPTS} times")
