from pathlib import Path

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    llm_api_key: SecretStr
    search_api_key: SecretStr | None = None
    llm_provider: str = "fake"
    search_provider: str = "fake"
    database_url: str = "sqlite+aiosqlite:///./data/agugent.db"
    openai_base_url: str | None = None
    deepseek_base_url: str = "https://api.deepseek.com"
    openai_model: str = "gpt-4o-mini"
    deepseek_model: str = "deepseek-chat"
    max_search_results: int = 10

    @property
    def database_path(self) -> Path:
        return Path(self.database_url.removeprefix("sqlite+aiosqlite:///"))
