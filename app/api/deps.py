from collections.abc import Callable
from functools import lru_cache
from typing import Annotated

from fastapi import Depends
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.core.errors import ServiceUnavailableError
from app.db.session import get_db, get_sessionmaker
from app.llm.base import LLMClient
from app.llm.openai_client import OpenAIClient
from app.storage.file_storage import FileStorage, LocalFileStorage
from app.workers.analysis_runner import AnalysisRunner

SettingsDep = Annotated[Settings, Depends(get_settings)]
DbSession = Annotated[Session, Depends(get_db)]


def get_storage(settings: SettingsDep) -> FileStorage:
    return LocalFileStorage(settings.storage_dir)


StorageDep = Annotated[FileStorage, Depends(get_storage)]


@lru_cache
def _openai_client(api_key: str, model: str, timeout: float, max_retries: int) -> OpenAIClient:
    # HTTP 커넥션 풀을 재사용하도록 같은 설정이면 같은 클라이언트를 돌려준다.
    return OpenAIClient(api_key=api_key, model=model, timeout=timeout, max_retries=max_retries)


def get_llm_client(settings: SettingsDep) -> LLMClient:
    if settings.openai_api_key is None:
        raise ServiceUnavailableError(
            "LLM_NOT_CONFIGURED", "The language model is not configured (OPENAI_API_KEY)."
        )
    return _openai_client(
        settings.openai_api_key.get_secret_value(),
        settings.llm_model,
        settings.llm_timeout_seconds,
        settings.llm_max_retries,
    )


def get_session_factory() -> Callable[[], Session]:
    return get_sessionmaker()


def get_analysis_runner(
    settings: SettingsDep,
    storage: StorageDep,
    llm: Annotated[LLMClient, Depends(get_llm_client)],
    session_factory: Annotated[Callable[[], Session], Depends(get_session_factory)],
) -> AnalysisRunner:
    return AnalysisRunner(
        session_factory=session_factory, storage=storage, llm=llm, settings=settings
    )
