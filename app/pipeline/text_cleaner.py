"""추출한 페이지 텍스트 정제와 품질 점검.

정제는 '검색·인용 대조에 방해되는 잡음'만 제거한다. 문장 내용은 바꾸지 않는다.
(근거 인용문을 원문과 대조해야 하므로 과도한 정제는 오히려 해가 된다.)
"""

import re
import unicodedata
from collections import Counter
from dataclasses import dataclass

from app.domain.analysis import AnalysisErrorCode, AnalysisFailure
from app.pipeline.pdf_extractor import PageText

_INLINE_SPACE = re.compile(r"[ \t\u00a0\u2000-\u200b\u3000]+")
_MANY_BLANK_LINES = re.compile(r"\n{3,}")
# "3", "- 3 -", "3 / 10", "Page 3", "3 페이지" 처럼 페이지 번호만 있는 줄
_PAGE_NUMBER_LINE = re.compile(
    r"^(?:[-\u2013\u2014]?\s*\d{1,4}\s*[-\u2013\u2014]?|\d{1,4}\s*/\s*\d{1,4}|page\s*\d{1,4}|\d{1,4}\s*페이지)$",
    re.IGNORECASE,
)
# 이 비율 이상의 페이지에서 첫 줄/마지막 줄로 반복되면 머리글·바닥글로 본다
_REPEATED_LINE_RATIO = 0.5
_MIN_PAGES_FOR_HEADER_DETECTION = 3
_EMPTY_PAGE_CHARS = 10


@dataclass(frozen=True)
class TextStats:
    page_count: int
    char_count: int  # 공백 제외 글자 수
    empty_pages: list[int]


def _normalize(text: str) -> list[str]:
    text = unicodedata.normalize("NFC", text).replace("\r\n", "\n").replace("\r", "\n")
    return [_INLINE_SPACE.sub(" ", line).strip() for line in text.split("\n")]


def _edge_lines(lines: list[str]) -> set[str]:
    non_empty = [line for line in lines if line]
    return {non_empty[0], non_empty[-1]} if non_empty else set()


def clean_pages(pages: list[PageText]) -> list[PageText]:
    normalized = [_normalize(page.text) for page in pages]

    repeated: set[str] = set()
    if len(pages) >= _MIN_PAGES_FOR_HEADER_DETECTION:
        counts = Counter(line for lines in normalized for line in _edge_lines(lines))
        threshold = len(pages) * _REPEATED_LINE_RATIO
        repeated = {line for line, count in counts.items() if count >= threshold}

    cleaned: list[PageText] = []
    for page, lines in zip(pages, normalized, strict=True):
        kept = [
            line for line in lines if line not in repeated and not _PAGE_NUMBER_LINE.match(line)
        ]
        text = _MANY_BLANK_LINES.sub("\n\n", "\n".join(kept)).strip()
        cleaned.append(PageText(page_no=page.page_no, text=text))
    return cleaned


def compute_stats(pages: list[PageText]) -> TextStats:
    char_counts = [len("".join(page.text.split())) for page in pages]
    return TextStats(
        page_count=len(pages),
        char_count=sum(char_counts),
        empty_pages=[
            page.page_no
            for page, count in zip(pages, char_counts, strict=True)
            if count < _EMPTY_PAGE_CHARS
        ],
    )


def ensure_analyzable(stats: TextStats, *, min_chars: int, max_chars: int) -> None:
    if stats.char_count < min_chars:
        raise AnalysisFailure(
            AnalysisErrorCode.NO_TEXT_LAYER,
            "No extractable text was found. The PDF may be scanned or image-based (OCR needed).",
        )
    if stats.char_count > max_chars:
        raise AnalysisFailure(
            AnalysisErrorCode.DOCUMENT_TOO_LARGE,
            f"The document has {stats.char_count} characters; the limit is {max_chars}.",
        )
