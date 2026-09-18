from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    database_url: str = "sqlite+aiosqlite:///./data/skill-runner.db"
    run_root: Path = Path("./data/runs")
    skill_path: Path = Path("./.agents/skills/zao-agugent-supervisor")
    dynamic_example_count: int = 3
    codex_command: str = "codex"

