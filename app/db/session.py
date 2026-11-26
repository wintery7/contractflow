from collections.abc import Iterator
from functools import lru_cache

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import get_settings


@lru_cache
def get_engine() -> Engine:
    # pool_pre_ping: DB 재시작 후 끊긴 커넥션을 재사용하다 실패하는 것을 막는다.
    return create_engine(get_settings().database_url, pool_pre_ping=True)


@lru_cache
def get_sessionmaker() -> sessionmaker[Session]:
    return sessionmaker(bind=get_engine(), autoflush=False, expire_on_commit=False)


def get_db() -> Iterator[Session]:
    """요청 하나당 세션 하나. 커밋은 서비스 계층이 유스케이스 단위로 직접 한다."""
    session = get_sessionmaker()()
    try:
        yield session
    finally:
        session.close()
