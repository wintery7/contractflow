"""실제 OpenAI 임베딩·LLM으로 검색과 근거 기반 답변을 확인한다. (uv run pytest -m live)

검색은 DB 없이 메모리에서 정확한 코사인 유사도로 계산한다 (운영과 같은 정확 검색).
"""

import uuid

import pytest

from app.core.config import Settings
from app.llm.embeddings import OpenAIEmbedder
from app.llm.openai_client import OpenAIClient
from app.pipeline.chunker import chunk_pages
from app.pipeline.pdf_extractor import PageText
from app.rag.answerer import chunk_label, generate_answer
from app.rag.retriever import RetrievedChunk
from tests.fixtures.sample_contract import SAMPLE_CONTRACT_PAGES

pytestmark = pytest.mark.live


@pytest.fixture(scope="module")
def settings() -> Settings:
    settings = Settings()
    if settings.openai_api_key is None:
        pytest.skip("OPENAI_API_KEY is not set")
    return settings


@pytest.fixture(scope="module")
def embedder(settings: Settings) -> OpenAIEmbedder:
    assert settings.openai_api_key is not None
    return OpenAIEmbedder(
        api_key=settings.openai_api_key.get_secret_value(),
        model=settings.embedding_model,
        dimensions=settings.embedding_dimensions,
        timeout=60,
        max_retries=1,
    )


@pytest.fixture(scope="module")
def llm(settings: Settings) -> OpenAIClient:
    assert settings.openai_api_key is not None
    return OpenAIClient(
        api_key=settings.openai_api_key.get_secret_value(),
        model=settings.llm_model,
        timeout=120,
        max_retries=1,
    )


@pytest.fixture(scope="module")
def index(embedder: OpenAIEmbedder, settings: Settings) -> list[tuple[RetrievedChunk, list[float]]]:
    pages = [PageText(i, t) for i, t in enumerate(SAMPLE_CONTRACT_PAGES, start=1)]
    chunks = chunk_pages(
        pages, max_chars=settings.chunk_max_chars, overlap_chars=settings.chunk_overlap_chars
    )
    vectors = embedder.embed([c.content for c in chunks]).vectors
    return [
        (RetrievedChunk(uuid.uuid4(), c.index, c.page_start, c.page_end, c.content, 0.0), v)
        for c, v in zip(chunks, vectors, strict=True)
    ]


def search(
    index: list[tuple[RetrievedChunk, list[float]]], embedder: OpenAIEmbedder, q: str, k: int = 3
) -> list[RetrievedChunk]:
    [qv] = embedder.embed([q]).vectors
    scored = [
        (sum(a * b for a, b in zip(qv, v, strict=True)), chunk) for chunk, v in index
    ]  # OpenAI 임베딩은 길이 1로 정규화되어 있어 내적 = 코사인 유사도
    scored.sort(key=lambda item: item[0], reverse=True)
    return [
        RetrievedChunk(c.chunk_id, c.chunk_index, c.page_start, c.page_end, c.content, round(s, 4))
        for s, c in scored[:k]
    ]


def test_termination_question_is_answered_from_article_7(
    index: list[tuple[RetrievedChunk, list[float]]], embedder: OpenAIEmbedder, llm: OpenAIClient
) -> None:
    retrieved = search(index, embedder, "계약을 중도에 해지하려면 어떤 조건이 필요한가요?")

    assert "제7조(계약의 해지)" in retrieved[0].content
    output = generate_answer(
        "계약을 중도에 해지하려면 어떤 조건이 필요한가요?", retrieved, llm, lambda _: None
    )

    assert output.answerable
    cited = [retrieved[i] for i in range(len(retrieved)) if chunk_label(i) in output.cited_chunks]
    assert any("제7조" in c.content for c in cited)


def test_question_not_covered_by_contract_is_declined(
    index: list[tuple[RetrievedChunk, list[float]]], embedder: OpenAIEmbedder, llm: OpenAIClient
) -> None:
    question = "이 계약의 준거법과 분쟁 시 관할 법원은 어디인가요?"
    retrieved = search(index, embedder, question)

    output = generate_answer(question, retrieved, llm, lambda _: None)

    assert not output.answerable
    assert output.answer is None
