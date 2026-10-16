"""PDF → 페이지별 텍스트.

페이지 번호를 보존하는 것이 핵심이다. 이후 구조화 추출의 근거(page, quote)와
RAG 청크의 출처 표시가 모두 이 page_no를 기준으로 한다.

한계: 텍스트 레이어가 없는 스캔/이미지 PDF는 글자가 추출되지 않는다.
OCR(예: Tesseract, 클라우드 OCR)은 이 인터페이스 뒤에 별도 구현으로 추가할 수 있다.
"""

from dataclasses import dataclass
from pathlib import Path

import pymupdf

from app.domain.analysis import AnalysisErrorCode, AnalysisFailure


@dataclass(frozen=True)
class PageText:
    page_no: int  # 1부터 시작
    text: str


def extract_pages(path: Path, *, max_pages: int) -> list[PageText]:
    try:
        document = pymupdf.open(path, filetype="pdf")
    except (pymupdf.FileDataError, RuntimeError, ValueError) as exc:
        raise AnalysisFailure(
            AnalysisErrorCode.PDF_UNREADABLE, "The PDF file is damaged or cannot be parsed."
        ) from exc

    with document:
        if document.needs_pass:
            raise AnalysisFailure(
                AnalysisErrorCode.PDF_ENCRYPTED, "Password-protected PDFs are not supported."
            )
        if document.page_count == 0:
            raise AnalysisFailure(AnalysisErrorCode.PDF_UNREADABLE, "The PDF has no pages.")
        if document.page_count > max_pages:
            raise AnalysisFailure(
                AnalysisErrorCode.DOCUMENT_TOO_LARGE,
                f"The PDF has {document.page_count} pages; the limit is {max_pages}.",
            )
        # sort=True: 다단/표 레이아웃에서도 위→아래, 왼쪽→오른쪽 읽기 순서에 가깝게 정렬
        return [
            PageText(page_no=index + 1, text=page.get_text("text", sort=True))
            for index, page in enumerate(document)
        ]
