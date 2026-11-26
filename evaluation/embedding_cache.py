"""평가용 임베딩 디스크 캐시. 같은 (모델, 텍스트)는 다시 호출하지 않는다 (비용 절감·재현성)."""

import hashlib
import json
from pathlib import Path

from app.llm.embeddings import Embedder

CACHE_DIR = Path(__file__).parent / ".cache"


class CachedEmbedder:
    def __init__(self, embedder: Embedder, cache_dir: Path = CACHE_DIR) -> None:
        self._embedder = embedder
        self.model = embedder.model
        cache_dir.mkdir(parents=True, exist_ok=True)
        self._path = cache_dir / f"embeddings-{embedder.model}-{embedder.dimensions}.json"
        self._cache: dict[str, list[float]] = (
            json.loads(self._path.read_text(encoding="utf-8")) if self._path.exists() else {}
        )
        self.api_calls = 0
        self.api_texts = 0

    @staticmethod
    def _key(text: str) -> str:
        return hashlib.sha256(text.encode("utf-8")).hexdigest()

    def embed(self, texts: list[str]) -> list[list[float]]:
        missing = list(dict.fromkeys(t for t in texts if self._key(t) not in self._cache))
        if missing:
            result = self._embedder.embed(missing)
            self.api_calls += 1
            self.api_texts += len(missing)
            for text, vector in zip(missing, result.vectors, strict=True):
                self._cache[self._key(text)] = vector
            self._path.write_text(json.dumps(self._cache), encoding="utf-8")
        return [self._cache[self._key(t)] for t in texts]
