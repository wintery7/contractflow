"""임베딩 공급자 추상화 (LLMClient와 같은 원칙: 서비스는 프로토콜에만 의존)."""

import hashlib
import math
from dataclasses import dataclass
from typing import Protocol

import openai
from openai import OpenAI

from app.llm.base import LLMRequestRejectedError, LLMUnavailableError

_OPENAI_BATCH_SIZE = 100


@dataclass(frozen=True)
class EmbeddingResult:
    vectors: list[list[float]]
    input_tokens: int | None


class Embedder(Protocol):
    provider: str
    model: str
    dimensions: int

    def embed(self, texts: list[str]) -> EmbeddingResult: ...


class OpenAIEmbedder:
    provider = "openai"

    def __init__(
        self, *, api_key: str, model: str, dimensions: int, timeout: float, max_retries: int
    ) -> None:
        self.model = model
        self.dimensions = dimensions
        self._client = OpenAI(api_key=api_key, timeout=timeout, max_retries=max_retries)

    def embed(self, texts: list[str]) -> EmbeddingResult:
        vectors: list[list[float]] = []
        tokens = 0
        for start in range(0, len(texts), _OPENAI_BATCH_SIZE):
            batch = texts[start : start + _OPENAI_BATCH_SIZE]
            try:
                response = self._client.embeddings.create(
                    model=self.model, input=batch, dimensions=self.dimensions
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
            ordered = sorted(response.data, key=lambda item: item.index)
            vectors.extend(item.embedding for item in ordered)
            tokens += response.usage.prompt_tokens if response.usage else 0
        return EmbeddingResult(vectors=vectors, input_tokens=tokens)


class FakeEmbedder:
    """테스트용 결정적 임베딩: 글자 2-gram을 해시해 벡터로 만든다.

    네트워크 없이도 '글자가 많이 겹치는 문장일수록 유사도가 높다'는 성질을 가져서
    검색 순서·근거 부족 처리 같은 로직을 의미 있게 테스트할 수 있다.
    """

    provider = "fake"
    model = "fake-embedding"

    def __init__(self, dimensions: int = 1536) -> None:
        self.dimensions = dimensions
        self.calls: list[list[str]] = []

    def embed(self, texts: list[str]) -> EmbeddingResult:
        self.calls.append(list(texts))
        return EmbeddingResult(vectors=[self._vector(t) for t in texts], input_tokens=len(texts))

    def _vector(self, text: str) -> list[float]:
        compact = "".join(text.split())
        vector = [0.0] * self.dimensions
        for i in range(len(compact) - 1):
            digest = hashlib.md5(compact[i : i + 2].encode(), usedforsecurity=False).digest()
            vector[int.from_bytes(digest[:4], "little") % self.dimensions] += 1.0
        norm = math.sqrt(sum(v * v for v in vector)) or 1.0
        return [v / norm for v in vector]
