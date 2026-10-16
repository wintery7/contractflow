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

    # 문서 처리 한도
    max_pages: int = Field(default=100, gt=0)
    # 구조화 추출에 한 번에 보낼 수 있는 최대 글자 수 (한국어는 대략 1~1.5자당 1토큰)
    max_analysis_chars: int = Field(default=120_000, gt=0)
    # 문서 전체 글자 수가 이보다 적으면 텍스트 레이어가 없는(스캔) PDF로 본다
    min_text_chars: int = Field(default=50, ge=0)

    # LLM
    openai_api_key: SecretStr | None = None
    llm_model: str = "gpt-5.4-mini"
    llm_timeout_seconds: float = Field(default=60.0, gt=0)
    # SDK가 429/5xx/타임아웃에 대해 지수 백오프로 재시도하는 횟수
    llm_max_retries: int = Field(default=2, ge=0)

    # 앱 시작 시 중단된(하트비트가 끊긴) 분석을 FAILED로 정리
    recover_stale_analyses_on_startup: bool = True
    analysis_stale_after_seconds: int = Field(default=900, gt=0)


@lru_cache
def get_settings() -> Settings:
    return Settings()
