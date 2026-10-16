"""테스트용 PDF 바이트 생성기 (외부 라이브러리 없이 최소한의 유효한 PDF를 만든다)."""


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
