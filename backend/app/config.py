from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = REPOSITORY_ROOT / "backend"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=REPOSITORY_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    database_url: str = f"sqlite+aiosqlite:///{BACKEND_ROOT / 'data/skill-runner.db'}"
    run_root: Path = BACKEND_ROOT / "data/runs"
    skill_path: Path = REPOSITORY_ROOT / "skill"
    dynamic_example_count: int = 3
    codex_command: str = "codex"
