"""키워드 검색(BM25)과 하이브리드(RRF) — 벡터 검색과 비교하기 위한 평가용 구현.

한국어는 조사가 붙어 띄어쓰기 단위가 검색에 불리하므로(예: '계약기간은', '계약기간을'),
형태소 분석기 없이 공백을 제거한 글자 2-gram을 토큰으로 쓴다.
"""

import math
from collections import Counter
from collections.abc import Sequence


def bigrams(text: str) -> list[str]:
    compact = "".join(text.split())
    return [compact[i : i + 2] for i in range(len(compact) - 1)]


class BM25:
    def __init__(self, documents: Sequence[str], k1: float = 1.5, b: float = 0.75) -> None:
        self._docs = [Counter(bigrams(d)) for d in documents]
        self._lengths = [sum(c.values()) for c in self._docs]
        self._avg_len = (sum(self._lengths) / len(self._lengths)) if self._lengths else 0.0
        self._k1, self._b = k1, b
        df: Counter[str] = Counter()
        for counts in self._docs:
            df.update(counts.keys())
        n = len(self._docs)
        self._idf = {t: math.log(1 + (n - f + 0.5) / (f + 0.5)) for t, f in df.items()}

    def scores(self, query: str) -> list[float]:
        terms = bigrams(query)
        result = []
        for counts, length in zip(self._docs, self._lengths, strict=True):
            score = 0.0
            norm = self._k1 * (1 - self._b + self._b * length / (self._avg_len or 1))
            for term in terms:
                tf = counts.get(term, 0)
                if tf:
                    score += self._idf[term] * tf * (self._k1 + 1) / (tf + norm)
            result.append(score)
        return result


def rank_by(scores: Sequence[float]) -> list[int]:
    """점수 내림차순 인덱스 (동점이면 앞 청크 우선)."""
    return sorted(range(len(scores)), key=lambda i: (-scores[i], i))


def reciprocal_rank_fusion(rankings: Sequence[Sequence[int]], k: int = 60) -> list[int]:
    """여러 순위를 합친다 (Reciprocal Rank Fusion).

    점수 척도가 다른 검색(코사인 vs BM25)을 섞을 때 순위만 쓰므로 안전하다.
    """
    fused: dict[int, float] = {}
    for ranking in rankings:
        for rank, index in enumerate(ranking, start=1):
            fused[index] = fused.get(index, 0.0) + 1.0 / (k + rank)
    return sorted(fused, key=lambda i: (-fused[i], i))
