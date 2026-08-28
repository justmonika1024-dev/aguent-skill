
import pytest

from app.config import Settings


def test_settings_require_llm_key_and_keep_it_secret(monkeypatch):
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    with pytest.raises(Exception):
        Settings(_env_file=None)

    settings = Settings(_env_file=None, llm_api_key="secret", search_api_key="exa")
    assert settings.llm_api_key.get_secret_value() == "secret"
    assert "secret" not in repr(settings)


def test_settings_defaults_to_sqlite_and_fake_providers():
    settings = Settings(_env_file=None, llm_api_key="x")
    assert settings.database_url.startswith("sqlite+aiosqlite:///")
    assert settings.llm_provider == "fake"
    assert settings.search_provider == "fake"
