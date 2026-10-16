import hashlib
import io

import pytest

from app.core.errors import BadRequestError, PayloadTooLargeError, UnsupportedMediaTypeError
from app.services.document_service import inspect_pdf
from tests.factories import make_pdf


def test_valid_pdf_returns_size_and_hash() -> None:
    data = make_pdf(["hello"])
    source = io.BytesIO(data)

    result = inspect_pdf(source, max_bytes=len(data))

    assert result.size_bytes == len(data)
    assert result.sha256 == hashlib.sha256(data).hexdigest()
    assert source.tell() == 0  # 저장을 위해 처음으로 되감아 둔다


def test_empty_file() -> None:
    with pytest.raises(BadRequestError) as exc_info:
        inspect_pdf(io.BytesIO(b""), max_bytes=100)
    assert exc_info.value.code == "EMPTY_FILE"


@pytest.mark.parametrize("data", [b"\x89PNG\r\n\x1a\n...", b"hello world", b"%PD"])
def test_non_pdf_content_is_rejected_regardless_of_extension(data: bytes) -> None:
    with pytest.raises(UnsupportedMediaTypeError):
        inspect_pdf(io.BytesIO(data), max_bytes=100)


def test_file_over_limit() -> None:
    data = make_pdf(["x" * 100])
    with pytest.raises(PayloadTooLargeError) as exc_info:
        inspect_pdf(io.BytesIO(data), max_bytes=len(data) - 1)
    assert exc_info.value.details == {"max_bytes": len(data) - 1}
