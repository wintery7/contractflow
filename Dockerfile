# syntax=docker/dockerfile:1

# ---------- 빌드 단계: 의존성 설치 ----------
FROM python:3.11.9-slim AS builder
COPY --from=ghcr.io/astral-sh/uv:0.12.5 /uv /bin/uv

WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never

# 의존성 목록만 먼저 복사해 설치한다. 코드만 바뀌면 이 레이어는 캐시를 재사용한다.
COPY pyproject.toml uv.lock .python-version ./
RUN uv sync --frozen --no-dev --no-install-project

COPY alembic.ini ./
COPY migrations ./migrations
COPY app ./app
RUN uv sync --frozen --no-dev

# ---------- 실행 단계: 최소 이미지 ----------
FROM python:3.11.9-slim

RUN useradd --create-home --uid 1000 appuser \
    && mkdir -p /data/uploads \
    && chown appuser:appuser /data/uploads

WORKDIR /app
COPY --from=builder --chown=appuser:appuser /app /app

ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    STORAGE_DIR=/data/uploads

USER appuser
EXPOSE 8000

HEALTHCHECK --interval=10s --timeout=3s --start-period=20s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health/live', timeout=2)"

# 데모 편의를 위해 시작 시 마이그레이션을 적용한다.
# 여러 인스턴스를 띄우는 운영 환경에서는 배포 파이프라인의 별도 단계로 분리해야 한다.
CMD ["sh", "-c", "alembic upgrade head && exec uvicorn app.main:app --host 0.0.0.0 --port 8000 --no-access-log"]
