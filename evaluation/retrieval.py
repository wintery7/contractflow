"""평가용 메모리 내 색인·검색. 운영과 같은 청커와 정확 코사인 검색을 쓴다."""

import math
from dataclasses import dataclass

from app.pipeline.chunker import Chunk, chunk_pages
from evaluation.dataset import contract_pages
from evaluation.datasets.contracts import CONTRACTS
from evaluation.embedding_cache import CachedEmbedder
from evaluation.lexical import BM25, rank_by, reciprocal_rank_fusion

METHODS = ("vector", "bm25", "hybrid")


@dataclass
class ContractIndex:
    chunks: list[Chunk]
    vectors: list[list[float]]
    bm25: BM25


def build_indexes(
    embedder: CachedEmbedder, *, max_chars: int, overlap_chars: int
) -> dict[str, ContractIndex]:
    indexes = {}
    for contract in CONTRACTS:
        chunks = chunk_pages(
            contract_pages(contract), max_chars=max_chars, overlap_chars=overlap_chars
        )
        texts = [c.content for c in chunks]
        indexes[contract] = ContractIndex(chunks, embedder.embed(texts), BM25(texts))
    return indexes


def cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    norm = math.sqrt(sum(x * x for x in a)) * math.sqrt(sum(y * y for y in b))
    return dot / norm if norm else 0.0


def vector_scores(index: ContractIndex, query_vector: list[float]) -> list[float]:
    return [cosine(query_vector, v) for v in index.vectors]


def rank(index: ContractIndex, method: str, query: str, query_vector: list[float]) -> list[int]:
    if method == "vector":
        return rank_by(vector_scores(index, query_vector))
    if method == "bm25":
        return rank_by(index.bm25.scores(query))
    if method == "hybrid":
        return reciprocal_rank_fusion(
            [rank_by(vector_scores(index, query_vector)), rank_by(index.bm25.scores(query))]
        )
    raise ValueError(method)
