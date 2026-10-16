"""테스트·로컬 개발용 Fake LLM. 네트워크 없이 결정적으로 동작한다."""

from collections.abc import Callable
from typing import Any

from app.llm.base import ChatMessage, LLMResult

Responder = Callable[[str, list[ChatMessage]], str]
Scripted = str | Exception


class FakeLLMClient:
    provider = "fake"

    def __init__(self, responses: list[Scripted] | Responder, model: str = "fake-model") -> None:
        """responses: 호출 순서대로 돌려줄 문자열/예외 목록, 또는 (system, messages) -> str 함수."""
        self.model = model
        self._responses = responses
        self.calls: list[list[ChatMessage]] = []

    def complete_json(
        self,
        *,
        system: str,
        messages: list[ChatMessage],
        schema_name: str,
        json_schema: dict[str, Any],
    ) -> LLMResult:
        self.calls.append(list(messages))
        if callable(self._responses):
            content = self._responses(system, messages)
        else:
            if not self._responses:
                raise AssertionError("FakeLLMClient has no scripted responses left")
            next_item = self._responses.pop(0)
            if isinstance(next_item, Exception):
                raise next_item
            content = next_item
        return LLMResult(content=content, model=self.model, input_tokens=100, output_tokens=50)
