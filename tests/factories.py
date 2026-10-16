"""테스트 데이터 생성기: PDF 바이트, LLM 추출 응답 JSON."""

import json
from typing import Any

import pymupdf


def _escape(text: str) -> str:
    return text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def make_pdf(page_texts: list[str] | None = None) -> bytes:
    """페이지마다 한 줄의 ASCII 텍스트를 가진 PDF를 만든다.

    내용이 다르면 SHA-256이 달라지므로 중복 업로드 테스트에서 텍스트로 파일을 구분한다.
    """
    page_texts = page_texts or ["Sample contract"]
    page_ids = [4 + 2 * i for i in range(len(page_texts))]

    objects: dict[int, bytes] = {
        1: b"<< /Type /Catalog /Pages 2 0 R >>",
        2: (
            f"<< /Type /Pages /Kids [{' '.join(f'{p} 0 R' for p in page_ids)}] "
            f"/Count {len(page_texts)} >>"
        ).encode(),
        3: b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    }
    for page_id, text in zip(page_ids, page_texts, strict=True):
        content_id = page_id + 1
        stream = f"BT /F1 12 Tf 72 720 Td ({_escape(text)}) Tj ET".encode("latin-1")
        objects[page_id] = (
            "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
            f"/Resources << /Font << /F1 3 0 R >> >> /Contents {content_id} 0 R >>"
        ).encode()
        objects[content_id] = (
            f"<< /Length {len(stream)} >>\nstream\n".encode() + stream + b"\nendstream"
        )

    out = bytearray(b"%PDF-1.4\n")
    offsets: dict[int, int] = {}
    for object_id in sorted(objects):
        offsets[object_id] = len(out)
        out += f"{object_id} 0 obj\n".encode() + objects[object_id] + b"\nendobj\n"

    xref_offset = len(out)
    size = max(objects) + 1
    out += f"xref\n0 {size}\n0000000000 65535 f \n".encode()
    for object_id in range(1, size):
        out += f"{offsets[object_id]:010d} 00000 n \n".encode()
    out += f"trailer\n<< /Size {size} /Root 1 0 R >>\nstartxref\n{xref_offset}\n%%EOF\n".encode()
    return bytes(out)


# ---------- PyMuPDF 기반 (한국어·이미지·암호화) ----------


def make_korean_pdf(page_texts: list[str]) -> bytes:
    """한글이 들어간 텍스트 레이어 PDF. 내장 CJK 폰트('korea')를 사용한다."""
    document = pymupdf.open()
    for text in page_texts:
        page = document.new_page()
        overflow = page.insert_textbox(
            pymupdf.Rect(50, 50, 545, 800), text, fontname="korea", fontsize=10
        )
        assert overflow >= 0, "test text does not fit on one page"
    return document.tobytes()


def make_image_only_pdf(pages: int = 1) -> bytes:
    """텍스트 레이어 없이 이미지만 있는 PDF (스캔 문서 흉내)."""
    document = pymupdf.open()
    for _ in range(pages):
        page = document.new_page()
        pixmap = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 50, 50), False)
        pixmap.clear_with(200)
        page.insert_image(pymupdf.Rect(72, 72, 300, 300), pixmap=pixmap)
    return document.tobytes()


def make_encrypted_pdf() -> bytes:
    document = pymupdf.open()
    document.new_page().insert_text((72, 72), "secret")
    return document.tobytes(encryption=pymupdf.PDF_ENCRYPT_AES_256, user_pw="u", owner_pw="o")


# ---------- LLM 응답 ----------


def not_found() -> dict[str, Any]:
    return {"status": "NOT_FOUND", "value": None, "evidence": []}


def found(value: Any, page: int, quote: str) -> dict[str, Any]:
    return {"status": "FOUND", "value": value, "evidence": [{"page": page, "quote": quote}]}


def extraction_payload(**overrides: Any) -> dict[str, Any]:
    """SAMPLE_CONTRACT_PAGES 기준으로 원문과 일치하는 정상 추출 결과."""
    payload: dict[str, Any] = {
        "contract_title": found(
            "소프트웨어 유지보수 용역계약서", 1, "소프트웨어 유지보수 용역계약서"
        ),
        "parties": found(
            [
                {"name": "주식회사 한빛데이터", "role": "갑"},
                {"name": "주식회사 누리시스템", "role": "을"},
            ],
            1,
            '주식회사 한빛데이터(이하 "갑"이라 한다)와 주식회사 누리시스템(이하 "을"이라 한다)',
        ),
        "start_date": found("2026-01-01", 1, "2026년 1월 1일부터"),
        "end_date": found("2026-12-31", 1, "2026년 12월 31일까지로 한다"),
        "contract_amount": found(
            {"amount": "36000000", "currency": "KRW"},
            1,
            "계약금액은 금 36,000,000원(부가가치세 별도)으로 한다",
        ),
        "auto_renewal": found(
            "만료 30일 전까지 갱신 거절 통지가 없으면 1년 자동 연장", 2, "1년간 자동 연장된다"
        ),
        "termination": found(
            "의무 위반 후 14일 내 미시정 시 해지, 갑은 30일 전 통지로 해지 가능",
            2,
            "갑은 30일 전에 서면으로 통지하여 본 계약을 해지할 수 있다",
        ),
        "penalty": found(
            "장애 복구 지체 1일당 월 용역대금의 1천분의 3", 2, "지체 1일당 월 용역대금의 1천분의 3"
        ),
        "payment_terms": found(
            "월 300만원, 검수 후 다음 달 15일까지 지급",
            1,
            "다음 달 15일까지 을의 지정 계좌로 지급한다",
        ),
        "confidentiality": found(
            "계약 종료 후 3년간 비밀유지", 3, "계약 종료 후 3년간 제3자에게 누설하여서는 아니 된다"
        ),
        "review_items": [
            {
                "title": "갑의 일방적 해지권",
                "reason": "갑만 30일 전 통지로 사유 없이 해지할 수 있어 을에게 불리하다.",
                "priority": "HIGH",
                "evidence": [
                    {
                        "page": 2,
                        "quote": "갑은 30일 전에 서면으로 통지하여 본 계약을 해지할 수 있다",
                    }
                ],
            }
        ],
    }
    payload.update(overrides)
    return payload


def extraction_json(**overrides: Any) -> str:
    return json.dumps(extraction_payload(**overrides), ensure_ascii=False)
