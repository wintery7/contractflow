from fastapi import FastAPI

from app.api import health
from app.api.body_limit import body_size_limit_middleware
from app.api.error_handlers import register_error_handlers
from app.api.v1 import api_router
from app.core.config import Settings, get_settings
from app.core.logging import configure_logging
from app.core.middleware import request_context_middleware

DESCRIPTION = """
계약서 PDF를 업로드하고 근거 기반 분석·질의응답·검토 업무를 관리하는 API.

- **인증 미구현**: 로컬 단일 사용자 데모 전용입니다.
- 분석 결과는 법률 자문이 아닌 검토 보조 자료입니다.
"""

# multipart 경계·헤더 등 파일 본문 외 오버헤드 허용치
MULTIPART_OVERHEAD_BYTES = 64 * 1024


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings.log_level)

    app = FastAPI(title="ContractFlow AI", version="0.1.0", description=DESCRIPTION)
    # 나중에 등록한 미들웨어가 바깥쪽에서 실행된다.
    # request_context를 가장 바깥에 두어 413 응답에도 X-Request-ID가 붙게 한다.
    app.middleware("http")(
        body_size_limit_middleware(settings.max_upload_bytes + MULTIPART_OVERHEAD_BYTES)
    )
    app.middleware("http")(request_context_middleware)
    register_error_handlers(app)
    app.include_router(health.router)
    app.include_router(api_router)
    return app


app = create_app()
