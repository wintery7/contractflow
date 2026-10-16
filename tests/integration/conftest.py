"""실제 PostgreSQL을 쓰는 통합 테스트 픽스처.

- 세션 시작 시 Alembic으로 스키마를 base → head 재구성 (마이그레이션 자체도 함께 검증)
- 테스트마다 바깥 트랜잭션을 열고, 서비스의 commit()은 SAVEPOINT로만 반영되게 한 뒤 롤백
  → 테스트끼리 데이터가 섞이지 않고, 서비스 코드는 운영과 똑같이 commit()을 호출한다.
"""

import os
from collections.abc import Callable, Iterator
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import Connection, Engine, create_engine, make_url
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from app.api.deps import get_llm_client, get_session_factory, get_storage
from app.core.config import Settings, get_settings
from app.db.session import get_db
from app.llm.fake import FakeLLMClient
from app.main import create_app
from app.storage.file_storage import LocalFileStorage
from tests.factories import extraction_json

PROJECT_ROOT = Path(__file__).resolve().parents[2]
MAX_UPLOAD_BYTES = 64 * 1024


def _resolve_test_database_url() -> str:
    """TEST_DATABASE_URL 환경변수가 없으면 앱 DATABASE_URL(.env 포함)의 DB 이름에 '_test'를 붙인다.

    같은 서버·계정을 쓰되 DB만 분리하므로 접속 정보를 두 번 관리하지 않아도 된다.
    """
    if explicit := os.environ.get("TEST_DATABASE_URL"):
        return explicit
    url = make_url(get_settings().database_url)
    return url.set(database=f"{url.database}_test").render_as_string(hide_password=False)


TEST_DATABASE_URL = _resolve_test_database_url()


@pytest.fixture(scope="session")
def engine() -> Iterator[Engine]:
    # 아래에서 스키마를 통째로 지웠다가 다시 만든다(downgrade base).
    # 실수로 개발/다른 프로젝트 DB를 가리키면 데이터가 날아가므로 이름으로 한 번 더 막는다.
    database = make_url(TEST_DATABASE_URL).database or ""
    if not database.endswith("_test"):
        pytest.fail(
            f"Refusing to run integration tests against database {database!r}: "
            "the test database name must end with '_test'.",
            pytrace=False,
        )

    engine = create_engine(TEST_DATABASE_URL)
    try:
        with engine.connect():
            pass
    except OperationalError as exc:
        pytest.fail(
            f"Test database {database!r} is not reachable. Check DATABASE_URL in .env, "
            "make sure the server is running and the database exists, "
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
def connection(engine: Engine) -> Iterator[Connection]:
    """테스트 하나 = 바깥 트랜잭션 하나. 끝나면 전부 롤백한다."""
    connection = engine.connect()
    outer = connection.begin()
    try:
        yield connection
    finally:
        outer.rollback()
        connection.close()


@pytest.fixture
def session_factory(connection: Connection) -> Callable[[], Session]:
    """운영처럼 요청·백그라운드 작업마다 새 세션을 만든다. commit()은 SAVEPOINT로만 반영된다."""

    def factory() -> Session:
        return Session(
            bind=connection,
            join_transaction_mode="create_savepoint",
            autoflush=False,
            expire_on_commit=False,
        )

    return factory


@pytest.fixture
def db_session(session_factory: Callable[[], Session]) -> Iterator[Session]:
    """테스트 코드에서 직접 데이터를 넣거나 확인할 때 쓰는 세션."""
    session = session_factory()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(
        _env_file=None,
        database_url=TEST_DATABASE_URL,
        storage_dir=tmp_path / "uploads",
        max_upload_bytes=MAX_UPLOAD_BYTES,
        openai_api_key=None,
        # 앱 시작 시 정리 작업이 테스트 바깥 트랜잭션 밖의 DB를 건드리지 않게 한다.
        recover_stale_analyses_on_startup=False,
    )


@pytest.fixture
def storage(settings: Settings) -> LocalFileStorage:
    return LocalFileStorage(settings.storage_dir)


@pytest.fixture
def fake_llm() -> FakeLLMClient:
    """기본: 항상 정상 추출 결과를 돌려준다. 테스트에서 responses를 바꿔 실패를 주입한다."""
    return FakeLLMClient(lambda _system, _messages: extraction_json())


@pytest.fixture
def app(
    session_factory: Callable[[], Session],
    settings: Settings,
    storage: LocalFileStorage,
    fake_llm: FakeLLMClient,
) -> FastAPI:
    def get_test_db() -> Iterator[Session]:
        session = session_factory()
        try:
            yield session
        finally:
            session.close()

    app = create_app(settings)
    app.dependency_overrides[get_db] = get_test_db
    app.dependency_overrides[get_session_factory] = lambda: session_factory
    app.dependency_overrides[get_settings] = lambda: settings
    app.dependency_overrides[get_storage] = lambda: storage
    app.dependency_overrides[get_llm_client] = lambda: fake_llm
    return app


@pytest.fixture
def client(app: FastAPI) -> Iterator[TestClient]:
    # TestClient는 응답 후 BackgroundTasks까지 끝난 뒤에 반환한다 → 분석 결과를 바로 확인 가능
    with TestClient(app) as test_client:
        yield test_client
