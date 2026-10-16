import unicodedata

import pytest

from app.domain.filename import DEFAULT_FILENAME, MAX_FILENAME_LENGTH, sanitize_filename


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("contract.pdf", "contract.pdf"),
        ("../../etc/passwd.pdf", "passwd.pdf"),
        ("..\\..\\windows\\system32\\a.pdf", "a.pdf"),
        ("evil\r\nX-Injected: 1.pdf", "evilX-Injected: 1.pdf"),
        ("  spaced.pdf  ", "spaced.pdf"),
        ("", DEFAULT_FILENAME),
        (None, DEFAULT_FILENAME),
        ("../", DEFAULT_FILENAME),
        ("...", DEFAULT_FILENAME),
    ],
)
def test_sanitize_filename(raw: str | None, expected: str) -> None:
    assert sanitize_filename(raw) == expected


def test_korean_nfd_is_normalized_to_nfc() -> None:
    nfd = unicodedata.normalize("NFD", "용역계약서.pdf")
    result = sanitize_filename(nfd)
    assert result == "용역계약서.pdf"
    assert unicodedata.is_normalized("NFC", result)


def test_long_filename_is_truncated_keeping_extension() -> None:
    result = sanitize_filename("가" * 400 + ".pdf")
    assert len(result) == MAX_FILENAME_LENGTH
    assert result.endswith(".pdf")
