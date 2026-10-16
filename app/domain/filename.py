"""업로드 파일명 정규화.

원본 파일명은 디스크 경로에 절대 쓰지 않는다(저장 키는 서버가 만든 UUID).
여기서 정리한 값은 화면 표시용 메타데이터로만 저장된다.
"""

import unicodedata

MAX_FILENAME_LENGTH = 255
DEFAULT_FILENAME = "document.pdf"


def sanitize_filename(raw: str | None) -> str:
    if not raw:
        return DEFAULT_FILENAME

    # 맥 등에서 올라온 NFD 한글("ㄱ+ㅖ+ㅇ…")을 NFC로 합친다.
    name = unicodedata.normalize("NFC", raw)
    # 경로 구분자 이후의 마지막 부분만 사용 (../../etc/passwd.pdf -> passwd.pdf)
    name = name.replace("\\", "/").rsplit("/", 1)[-1]
    # 제어 문자 제거 (개행으로 로그/헤더를 오염시키는 것 방지)
    name = "".join(ch for ch in name if unicodedata.category(ch)[0] != "C")
    name = name.strip().strip(".")

    if not name:
        return DEFAULT_FILENAME

    if len(name) > MAX_FILENAME_LENGTH:
        stem, dot, ext = name.rpartition(".")
        if dot and len(ext) <= 10:
            name = stem[: MAX_FILENAME_LENGTH - len(ext) - 1] + "." + ext
        else:
            name = name[:MAX_FILENAME_LENGTH]
    return name
