"""실제 PostgreSQL을 쓰는 통합 테스트 픽스처.

- 세션 시작 시 Alembic으로 스키마를 base → head 재구성 (마이그레이션 자체도 함께 검증)
- 테스트마다 바깥 트랜잭션을 열고, 서비스의 commit()은 SAVEPOINT로만 반영되게 한 뒤 롤백
  → 테스트끼리 데이터가 섞이지 않고, 서비스 코드는 운영과 똑같이 commit()을 호출한다.
"""

import os
from collections.abc import Iterator
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import Engine, create_engine
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from app.api.deps import get_storage
from app.core.config import Settings, get_settings
from app.db.session import get_db
from app.main import create_app
from app.storage.file_storage import LocalFileStorage

PROJECT_ROOT = Path(__file__).resolve().parents[2]
TEST_DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL",
    "postgresql+psycopg://contractflow:change-me@localhost:5432/contractflow_test",
)
MAX_UPLOAD_BYTES = 64 * 1024


@pytest.fixture(scope="session")
def engine() -> Iterator[Engine]:
    engine = create_engine(TEST_DATABASE_URL)
    try:
        with engine.connect():
            pass
    except OperationalError as exc:
        pytest.fail(
            "Test database is not reachable. Start it with "
            "`uv run python scripts/local_db.py start` (or `docker compose up -d db`), "
            "or set TEST_DATABASE_URL. "
            f"({exc.__class__.__name__})",
            pytrace=False,
        )

    config = Config(str(PROJECT_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(PROJECT_ROOT / "migrations"))
    config.attributes["database_url"] = TEST_DATABASE_URL
    config.attributes["configure_logger"] = False
    command.downgrade(config, "base")
    command.upgrade(config, "head")

    yield engine
    engine.dispose()


@pytest.fixture
def db_session(engine: Engine) -> Iterator[Session]:
    connection = engine.connect()
    outer = connection.begin()
    session = Session(
        bind=connection,
        join_transaction_mode="create_savepoint",
        autoflush=False,
        expire_on_commit=False,
    )
    try:
        yield session
    finally:
        session.close()
        outer.rollback()
        connection.close()


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(
        _env_file=None,
        database_url=TEST_DATABASE_URL,
        storage_dir=tmp_path / "uploads",
        max_upload_bytes=MAX_UPLOAD_BYTES,
    )


@pytest.fixture
def storage(settings: Settings) -> LocalFileStorage:
    return LocalFileStorage(settings.storage_dir)


@pytest.fixture
def client(
    db_session: Session, settings: Settings, storage: LocalFileStorage
) -> Iterator[TestClient]:
    app = create_app(settings)
    app.dependency_overrides[get_db] = lambda: db_session
    app.dependency_overrides[get_settings] = lambda: settings
    app.dependency_overrides[get_storage] = lambda: storage
    with TestClient(app) as test_client:
        yield test_client
