from pathlib import Path

from app.api import create_app
from app.config import Settings
from tests.fakes import FakeRunner, VALID_RESULT


PACKAGE_ROOT = Path(__file__).parents[1]
REPOSITORY_ROOT = PACKAGE_ROOT.parent


def test_repository_layout_has_root_launcher_backend_and_skill():
    assert (REPOSITORY_ROOT / "start.sh").is_file()
    assert (REPOSITORY_ROOT / "README.md").is_file()
    assert (REPOSITORY_ROOT / ".env.example").is_file()
    assert (REPOSITORY_ROOT / "backend" / "app" / "main.py").is_file()
    assert (REPOSITORY_ROOT / "backend" / "pyproject.toml").is_file()
    assert (REPOSITORY_ROOT / "skill" / "SKILL.md").is_file()

    gitignore = (REPOSITORY_ROOT / ".gitignore").read_text(encoding="utf-8")
    assert ".env" in gitignore.splitlines()

    launcher = (REPOSITORY_ROOT / "start.sh").read_text(encoding="utf-8")
    assert "UV_CACHE_DIR" in launcher
    assert "uv sync --project" in launcher
    assert "--app-dir" in launcher
    assert "--workers 1" in launcher


def test_operator_files_cover_required_configuration_and_usage():
    environment = (REPOSITORY_ROOT / ".env.example").read_text(encoding="utf-8")
    readme = (REPOSITORY_ROOT / "README.md").read_text(encoding="utf-8")

    for name in (
        "DATABASE_URL",
        "RUN_ROOT",
        "SKILL_PATH",
        "DYNAMIC_EXAMPLE_COUNT",
        "CODEX_COMMAND",
    ):
        assert f"{name}=" in environment
    assert "POST /api/runs" in readme
    assert "GET /api/runs/{run_id}" in readme
    assert "MANUAL_SEED" in readme
    assert "AUTO" in readme
    assert "formal_memes" in readme
    assert "run_logs" in readme
    assert "./start.sh" in readme
    assert "uv sync --project backend --extra dev --frozen" in readme


def test_application_exposes_run_creation_and_evaluation_routes(tmp_path):
    skill = tmp_path / "skill"
    skill.mkdir()
    app = create_app(
        Settings(
            database_url=f"sqlite+aiosqlite:///{tmp_path / 'runner.db'}",
            run_root=tmp_path / "runs",
            skill_path=skill,
        ),
        FakeRunner(VALID_RESULT),
    )

    application_routes = {
        (method, route.path)
        for route in app.routes
        if route.path not in {"/openapi.json", "/docs", "/docs/oauth2-redirect", "/redoc"}
        for method in (route.methods or set())
    }
    assert application_routes == {
        ("POST", "/api/runs"),
        ("GET", "/api/runs/{run_id}"),
        ("POST", "/api/runs/{run_id}/evaluation"),
        ("GET", "/api/formal-memes"),
    }
