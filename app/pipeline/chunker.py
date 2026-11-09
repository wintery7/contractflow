"""페이지 텍스트 → 검색 단위 청크.

원칙
- 출처 보존: 모든 청크는 자신이 걸친 페이지 범위(page_start~page_end)를 가진다.
- 조항 경계 우선: "제N조"로 시작하는 줄에서 새 청크를 시작하려고 한다.
  계약서 질문은 대부분 '특정 조항'에 관한 것이라 조항이 쪼개지지 않을수록 검색이 정확하다.
- 크기 제한: 청크는 max_chars를 넘지 않는다. 긴 조항은 문장 단위로, 그래도 길면 글자 수로 자른다.
- 겹침(overlap): 앞 청크의 끝부분을 다음 청크 앞에 붙여 경계에 걸친 문장이 끊기지 않게 한다.
"""

import re
from dataclasses import dataclass

from app.pipeline.pdf_extractor import PageText

_ARTICLE_START = re.compile(r"^\s*제\s*\d+\s*조")
_SENTENCE_END = re.compile(r"(?<=[.!?。])\s+|(?<=다\.)")


@dataclass(frozen=True)
class Chunk:
    index: int
    page_start: int
    page_end: int
    content: str


@dataclass(frozen=True)
class _Segment:
    page_no: int
    text: str
    starts_article: bool


def _split_long(text: str, max_chars: int) -> list[str]:
    """max_chars보다 긴 문단을 문장 단위로, 그래도 길면 글자 수로 나눈다."""
    if len(text) <= max_chars:
        return [text]
    parts: list[str] = []
    current = ""
    for sentence in (s for s in _SENTENCE_END.split(text) if s and s.strip()):
        while len(sentence) > max_chars:
            if current:
                parts.append(current)
                current = ""
            parts.append(sentence[:max_chars])
            sentence = sentence[max_chars:]
        if current and len(current) + 1 + len(sentence) > max_chars:
            parts.append(current)
            current = sentence
        else:
            current = f"{current} {sentence}".strip() if current else sentence
    if current:
        parts.append(current)
    return parts


def _flush(block: list[str], page_no: int, max_chars: int, out: list[_Segment]) -> None:
    if not block:
        return
    text = "\n".join(block).strip()
    starts_article = bool(_ARTICLE_START.match(text))
    for i, part in enumerate(_split_long(text, max_chars)):
        out.append(_Segment(page_no, part, starts_article and i == 0))
    block.clear()


def _segments(pages: list[PageText], max_chars: int) -> list[_Segment]:
    """페이지를 문단 단위 조각으로 나눈다. 빈 줄과 '제N조' 줄이 조각의 경계다."""
    segments: list[_Segment] = []
    for page in pages:
        block: list[str] = []
        for line in page.text.split("\n"):
            if not line.strip():
                _flush(block, page.page_no, max_chars, segments)
                continue
            if _ARTICLE_START.match(line):
                _flush(block, page.page_no, max_chars, segments)
            block.append(line)
        _flush(block, page.page_no, max_chars, segments)
    return segments


def chunk_pages(pages: list[PageText], *, max_chars: int, overlap_chars: int) -> list[Chunk]:
    if overlap_chars >= max_chars:
        raise ValueError("overlap_chars must be smaller than max_chars")

    chunks: list[Chunk] = []
    current: list[_Segment] = []
    # 조항 경계에서 끊을지 판단할 때, 너무 작은 조각이 남지 않게 하는 최소 길이
    min_chars_before_article_break = max_chars // 3

    def size(segments: list[_Segment]) -> int:
        return sum(len(s.text) for s in segments) + max(len(segments) - 1, 0)

    def emit() -> None:
        chunks.append(
            Chunk(
                index=len(chunks),
                page_start=min(s.page_no for s in current),
                page_end=max(s.page_no for s in current),
                content="\n".join(s.text for s in current),
            )
        )

    def overlap_tail() -> list[_Segment]:
        if overlap_chars == 0:
            return []
        tail: list[_Segment] = []
        for segment in reversed(current):
            if size([segment, *tail]) > overlap_chars:
                if not tail:  # 마지막 조각이 길면 그 끝부분만 가져온다
                    tail = [_Segment(segment.page_no, segment.text[-overlap_chars:], False)]
                break
            tail.insert(0, segment)
        return tail

    for segment in _segments(pages, max_chars):
        new_size = size([*current, segment])
        article_break = segment.starts_article and size(current) >= min_chars_before_article_break
        if current and (new_size > max_chars or article_break):
            emit()
            current = overlap_tail()
            # 겹침을 붙였더니 넘치면 겹침을 줄인다
            while current and size([*current, segment]) > max_chars:
                current.pop(0)
        current.append(segment)

    if current:
        emit()
    return chunks
