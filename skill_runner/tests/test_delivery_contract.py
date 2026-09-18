from pathlib import Path

from app.api import create_app
from app.config import Settings
from tests.fakes import FakeRunner, VALID_RESULT


PACKAGE_ROOT = Path(__file__).parents[1]


def test_operator_files_cover_required_configuration_and_usage():
    environment = (PACKAGE_ROOT / ".env.example").read_text(encoding="utf-8")
    readme = (PACKAGE_ROOT / "README.md").read_text(encoding="utf-8")

    for name in (
        "DATABASE_URL",
        "RUN_ROOT",
        "SKILL_PATH",
        "DYNAMIC_EXAMPLE_COUNT",
        "CODEX_COMMAND",
    ):
        assert f"{name}=" in environment
    assert "POST /api/runs" in readme
    assert "MANUAL_SEED" in readme
    assert "AUTO" in readme
    assert "formal_memes" in readme
    assert "run_logs" in readme


def test_application_exposes_only_the_run_creation_route(tmp_path):
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
    assert application_routes == {("POST", "/api/runs")}
