from typing import Any

import openai
from openai import OpenAI
from openai.types.chat import ChatCompletionMessageParam

from app.llm.base import (
    ChatMessage,
    LLMRequestRejectedError,
    LLMResult,
    LLMUnavailableError,
)


class OpenAIClient:
    """OpenAI Chat Completions + Structured Outputs(json_schema, strict).

    재시도: SDK가 연결 오류·408·409·429·5xx에 대해 지수 백오프로 max_retries번 재시도한다.
    그 뒤에도 실패하면 LLMUnavailableError로 바꿔 올린다. 4xx 검증/인증 오류는 재시도하지 않는다.
    """

    provider = "openai"

    def __init__(self, *, api_key: str, model: str, timeout: float, max_retries: int) -> None:
        self.model = model
        self._client = OpenAI(api_key=api_key, timeout=timeout, max_retries=max_retries)

    def complete_json(
        self,
        *,
        system: str,
        messages: list[ChatMessage],
        schema_name: str,
        json_schema: dict[str, Any],
    ) -> LLMResult:
        payload: list[ChatCompletionMessageParam] = [{"role": "system", "content": system}]
        payload += [{"role": m.role, "content": m.content} for m in messages]
        try:
            response = self._client.chat.completions.create(
                model=self.model,
                messages=payload,
                response_format={
                    "type": "json_schema",
                    "json_schema": {"name": schema_name, "strict": True, "schema": json_schema},
                },
            )
        except (
            openai.APITimeoutError,
            openai.APIConnectionError,
            openai.RateLimitError,
            openai.InternalServerError,
        ) as exc:
            raise LLMUnavailableError(type(exc).__name__) from exc
        except openai.APIStatusError as exc:
            raise LLMRequestRejectedError(f"status={exc.status_code}") from exc

        message = response.choices[0].message
        usage = response.usage
        return LLMResult(
            # 모델이 거부(refusal)하면 content가 비어 있다 → 호출한 쪽 검증에서 실패 처리된다.
            content=message.content or "",
            model=response.model,
            input_tokens=usage.prompt_tokens if usage else None,
            output_tokens=usage.completion_tokens if usage else None,
        )
