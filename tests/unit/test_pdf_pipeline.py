from pathlib import Path

import pytest

from app.domain.analysis import AnalysisErrorCode, AnalysisFailure
from app.pipeline.pdf_extractor import PageText, extract_pages
from app.pipeline.text_cleaner import clean_pages, compute_stats, ensure_analyzable
from tests.factories import make_encrypted_pdf, make_image_only_pdf, make_korean_pdf
from tests.fixtures.sample_contract import SAMPLE_CONTRACT_PAGES


def write(tmp_path: Path, data: bytes) -> Path:
    path = tmp_path / "doc.pdf"
    path.write_bytes(data)
    return path


# ---------- 추출 ----------


def test_extracts_korean_text_with_page_numbers(tmp_path: Path) -> None:
    pages = extract_pages(write(tmp_path, make_korean_pdf(SAMPLE_CONTRACT_PAGES)), max_pages=10)

    assert [p.page_no for p in pages] == [1, 2, 3]
    assert "제2조(계약기간)" in pages[0].text
    assert "제6조(지체상금)" in pages[1].text
    assert "제8조(비밀유지)" in pages[2].text


def test_image_only_pdf_has_no_text(tmp_path: Path) -> None:
    pages = extract_pages(write(tmp_path, make_image_only_pdf(pages=2)), max_pages=10)
    assert [p.text.strip() for p in pages] == ["", ""]


@pytest.mark.parametrize(
    ("data", "code"),
    [
        (make_encrypted_pdf(), AnalysisErrorCode.PDF_ENCRYPTED),
        (b"%PDF-1.4 this is not really a pdf", AnalysisErrorCode.PDF_UNREADABLE),
    ],
)
def test_unreadable_pdfs(tmp_path: Path, data: bytes, code: AnalysisErrorCode) -> None:
    with pytest.raises(AnalysisFailure) as exc_info:
        extract_pages(write(tmp_path, data), max_pages=10)
    assert exc_info.value.code == code


def test_too_many_pages(tmp_path: Path) -> None:
    path = write(tmp_path, make_korean_pdf(["가", "나", "다"]))
    with pytest.raises(AnalysisFailure) as exc_info:
        extract_pages(path, max_pages=2)
    assert exc_info.value.code == AnalysisErrorCode.DOCUMENT_TOO_LARGE


# ---------- 정제 ----------


def test_removes_repeated_headers_footers_and_page_numbers() -> None:
    pages = [PageText(i, f"한빛데이터 대외비\n제{i}조 본문 내용 {i}\n- {i} -") for i in range(1, 5)]

    cleaned = clean_pages(pages)

    for i, page in enumerate(cleaned, start=1):
        assert page.text == f"제{i}조 본문 내용 {i}"


def test_header_detection_needs_enough_pages() -> None:
    # 두 페이지뿐이면 반복 판단 근거가 약하므로 지우지 않는다.
    pages = [PageText(1, "계약서\n본문1"), PageText(2, "계약서\n본문2")]
    assert [p.text for p in clean_pages(pages)] == ["계약서\n본문1", "계약서\n본문2"]


def test_normalizes_whitespace_and_unicode() -> None:
    import unicodedata

    nfd = unicodedata.normalize("NFD", "계약\u00a0\u00a0기간")
    [page] = clean_pages([PageText(1, f"{nfd}\r\n\n\n\n제2조")])
    assert page.text == "계약 기간\n\n제2조"


# ---------- 품질 점검 ----------


def test_stats_report_empty_pages() -> None:
    stats = compute_stats(
        [PageText(1, "가나다라마바사아자차카"), PageText(2, " \n "), PageText(3, "짧음")]
    )
    assert stats.page_count == 3
    assert stats.char_count == 13
    assert stats.empty_pages == [2, 3]


def test_no_text_layer() -> None:
    stats = compute_stats([PageText(1, "")])
    with pytest.raises(AnalysisFailure) as exc_info:
        ensure_analyzable(stats, min_chars=50, max_chars=1000)
    assert exc_info.value.code == AnalysisErrorCode.NO_TEXT_LAYER


def test_too_much_text() -> None:
    stats = compute_stats([PageText(1, "가" * 101)])
    with pytest.raises(AnalysisFailure) as exc_info:
        ensure_analyzable(stats, min_chars=1, max_chars=100)
    assert exc_info.value.code == AnalysisErrorCode.DOCUMENT_TOO_LARGE
