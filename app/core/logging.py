"""JSON 한 줄 로그와 요청 ID 컨텍스트.

원칙: 로그에는 식별자·길이·소요 시간·오류 코드만 남기고,
계약서 원문/질문/답변/API 키는 남기지 않는다. 혹시 메시지에 섞여 들어온 키 패턴은 마스킹한다.
"""

import json
import logging
import re
from contextvars import ContextVar
from datetime import UTC, datetime

request_id_var: ContextVar[str | None] = ContextVar("request_id", default=None)

_SECRET_PATTERN = re.compile(r"sk-[A-Za-z0-9_\-]{8,}")
_RESERVED = set(vars(logging.makeLogRecord({})))


def mask_secrets(text: str) -> str:
    return _SECRET_PATTERN.sub("sk-***", text)


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, object] = {
            "timestamp": datetime.fromtimestamp(record.created, tz=UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": mask_secrets(record.getMessage()),
            "request_id": request_id_var.get(),
        }
        # logger.info("...", extra={"document_id": ...}) 로 넘긴 필드
        for key, value in vars(record).items():
            if key not in _RESERVED and not key.startswith("_"):
                payload[key] = value
        if record.exc_info:
            payload["exception"] = mask_secrets(self.formatException(record.exc_info))
        return json.dumps(payload, ensure_ascii=False, default=str)


class _AppLogHandler(logging.StreamHandler):  # type: ignore[type-arg]
    """우리가 붙인 핸들러를 식별하기 위한 표식 클래스."""


def configure_logging(level: str) -> None:
    # 여러 번 호출돼도(테스트에서 앱을 반복 생성) 핸들러가 중복되지 않게 하고,
    # pytest 등 다른 곳에서 붙인 핸들러는 건드리지 않는다.
    root = logging.getLogger()
    for existing in [h for h in root.handlers if isinstance(h, _AppLogHandler)]:
        root.removeHandler(existing)
    handler = _AppLogHandler()
    handler.setFormatter(JsonFormatter())
    root.addHandler(handler)
    root.setLevel(level.upper())
