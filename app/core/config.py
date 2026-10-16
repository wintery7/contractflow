from functools import lru_cache
from pathlib import Path

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """환경변수(.env 포함)에서 읽는 애플리케이션 설정.

    비밀값은 SecretStr로 감싸 repr/로그에 노출되지 않게 한다.
    """

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_env: str = "local"
    log_level: str = "INFO"

    database_url: str = "postgresql+psycopg://contractflow:change-me@localhost:5432/contractflow"

    storage_dir: Path = Path("var/uploads")
    max_upload_bytes: int = Field(default=20 * 1024 * 1024, gt=0)

    openai_api_key: SecretStr | None = None


@lru_cache
def get_settings() -> Settings:
    return Settings()
