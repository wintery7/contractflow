"""LLM 공급자 추상화.

서비스 코드는 이 프로토콜에만 의존한다. 공급자를 바꾸거나 테스트에서 Fake로 교체해도
구조화 추출·검증 로직은 그대로다.
"""

from dataclasses import dataclass
from typing import Any, Literal, Protocol


@dataclass(frozen=True)
class ChatMessage:
    role: Literal["user", "assistant"]
    content: str


@dataclass(frozen=True)
class LLMResult:
    content: str  # 모델이 반환한 원본 텍스트(JSON 문자열). 검증은 호출한 쪽에서 한다.
    model: str
    input_tokens: int | None
    output_tokens: int | None


class LLMError(Exception):
    pass


class LLMUnavailableError(LLMError):
    """타임아웃·연결 실패·429·5xx 등 재시도해도 회복되지 않은 일시적 장애."""


class LLMRequestRejectedError(LLMError):
    """인증 실패·잘못된 요청·컨텍스트 초과 등 재시도해도 소용없는 4xx 오류."""


class LLMClient(Protocol):
    provider: str
    model: str

    def complete_json(
        self,
        *,
        system: str,
        messages: list[ChatMessage],
        schema_name: str,
        json_schema: dict[str, Any],
    ) -> LLMResult: ...
