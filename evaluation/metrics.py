"""검색·답변 평가 지표.

- 관련 청크: 정답 근거 구절(evidence) 중 하나라도 그대로 포함한 청크 (공백 무시)
- Recall@k (hit rate): 상위 k개 안에 관련 청크가 하나라도 있는 질문의 비율
- Evidence coverage@k: 정답 근거 구절 중 상위 k개 청크에 들어 있는 비율의 평균
  (여러 문장에 걸친 조건을 모두 찾아왔는지 본다)
- MRR@k: 첫 관련 청크 순위의 역수 평균 (상위 k개 밖이면 0)
"""

import math
import unicodedata
from collections.abc import Sequence


def squash(text: str) -> str:
    return "".join(unicodedata.normalize("NFC", text).split())


def is_relevant(chunk_text: str, evidence: Sequence[str]) -> bool:
    body = squash(chunk_text)
    return any(squash(snippet) in body for snippet in evidence)


def first_relevant_rank(ranked_texts: Sequence[str], evidence: Sequence[str]) -> int | None:
    for rank, text in enumerate(ranked_texts, start=1):
        if is_relevant(text, evidence):
            return rank
    return None


def hit_at_k(rank: int | None, k: int) -> float:
    return 1.0 if rank is not None and rank <= k else 0.0


def reciprocal_rank(rank: int | None, k: int) -> float:
    return 1.0 / rank if rank is not None and rank <= k else 0.0


def evidence_coverage(ranked_texts: Sequence[str], evidence: Sequence[str], k: int) -> float:
    if not evidence:
        return 0.0
    top = squash("\n".join(ranked_texts[:k]))
    return sum(squash(snippet) in top for snippet in evidence) / len(evidence)


def mean(values: Sequence[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def percentile(values: Sequence[float], p: float) -> float:
    """선형 보간 백분위수 (numpy 'linear'와 같은 방식)."""
    if not values:
        return 0.0
    ordered = sorted(values)
    position = (len(ordered) - 1) * p / 100
    low, high = math.floor(position), math.ceil(position)
    if low == high:
        return ordered[low]
    return ordered[low] + (ordered[high] - ordered[low]) * (position - low)
