import json
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

from app.api import create_app
from app.config import Settings
from tests.fakes import FakeRunner, VALID_RESULT


def make_settings(tmp_path: Path) -> Settings:
    skill = tmp_path / "source-skill"
    skill.mkdir()
    (skill / "SKILL.md").write_text("# fixture skill\n", encoding="utf-8")
    return Settings(
        database_url=f"sqlite+aiosqlite:///{tmp_path / 'runner.db'}",
        run_root=tmp_path / "runs",
        skill_path=skill,
    )


@pytest.fixture
async def client(tmp_path):
    app = create_app(make_settings(tmp_path), FakeRunner(VALID_RESULT))
    async with app.router.lifespan_context(app):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test",
        ) as http:
            yield http, app


@pytest.mark.parametrize(
    "payload",
    [
        {"mode": "MANUAL_SEED", "seed_text": "人工原梗"},
        {"mode": "AUTO"},
    ],
)
async def test_valid_request_is_accepted(client, payload):
    http, app = client

    response = await http.post("/api/runs", json=payload)

    assert response.status_code == 202
    assert response.json()["status"] == "PENDING"
    assert response.json()["run_id"]
    await app.state.run_service.wait_for_idle()


@pytest.mark.parametrize(
    "payload",
    [
        {"mode": "MANUAL_SEED"},
        {"mode": "MANUAL_SEED", "seed_text": "  "},
        {"mode": "AUTO", "seed_text": "不允许"},
        {"mode": "UNKNOWN"},
        {"mode": "AUTO", "unexpected": True},
    ],
)
async def test_invalid_request_is_rejected(client, payload):
    http, _ = client

    response = await http.post("/api/runs", json=payload)

    assert response.status_code == 422


async def test_active_run_returns_conflict(tmp_path):
    runner = FakeRunner(VALID_RESULT, blocked=True)
    app = create_app(make_settings(tmp_path), runner)
    async with app.router.lifespan_context(app):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test",
        ) as http:
            first = await http.post("/api/runs", json={"mode": "AUTO"})
            await runner.started.wait()
            second = await http.post("/api/runs", json={"mode": "AUTO"})
            runner.release.set()
            await app.state.run_service.wait_for_idle()

            assert first.status_code == 202
            assert second.status_code == 409
            assert second.json() == {
                "error": {
                    "code": "ACTIVE_RUN_EXISTS",
                    "message": "another run is active",
                },
            }


async def test_no_read_endpoints_are_exposed(client):
    http, _ = client

    for path in ("/", "/api/runs", "/api/logs", "/api/formal-memes"):
        response = await http.get(path)
        assert response.status_code in {404, 405}


async def test_startup_rejects_missing_skill(tmp_path):
    settings = Settings(
        database_url=f"sqlite+aiosqlite:///{tmp_path / 'runner.db'}",
        run_root=tmp_path / "runs",
        skill_path=tmp_path / "missing-skill",
    )
    app = create_app(settings, FakeRunner(VALID_RESULT))

    with pytest.raises(RuntimeError, match="SKILL_PATH"):
        async with app.router.lifespan_context(app):
            pass


async def test_startup_rejects_missing_codex_command(tmp_path):
    settings = make_settings(tmp_path)
    settings.codex_command = "codex-command-that-does-not-exist"
    app = create_app(settings)

    with pytest.raises(RuntimeError, match="CODEX_COMMAND"):
        async with app.router.lifespan_context(app):
            pass


async def test_startup_rejects_unusable_run_root(tmp_path):
    settings = make_settings(tmp_path)
    settings.run_root.write_text("not a directory", encoding="utf-8")
    app = create_app(settings, FakeRunner(VALID_RESULT))

    with pytest.raises(RuntimeError, match="RUN_ROOT"):
        async with app.router.lifespan_context(app):
            pass


async def test_startup_seeds_curated_runs_once(tmp_path):
    settings = make_settings(tmp_path)
    first_app = create_app(settings, FakeRunner(VALID_RESULT))
    async with first_app.router.lifespan_context(first_app):
        first_titles = await first_app.state.repository.list_formal_titles()

    second_app = create_app(settings, FakeRunner(VALID_RESULT))
    async with second_app.router.lifespan_context(second_app):
        second_titles = await second_app.state.repository.list_formal_titles()

    assert len(first_titles) == 5
    assert second_titles == first_titles


async def test_auto_run_injects_three_curated_dynamic_examples(tmp_path):
    settings = make_settings(tmp_path)
    settings.dynamic_example_count = 3
    runner = FakeRunner(VALID_RESULT)
    app = create_app(settings, runner)
    async with app.router.lifespan_context(app):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test",
        ) as http:
            response = await http.post("/api/runs", json={"mode": "AUTO"})
            assert response.status_code == 202
            await app.state.run_service.wait_for_idle()

    prompt = runner.calls[0][0]
    example_json = prompt.split("AUTO 动态示例：\n\n```json\n", 1)[1].split("\n```", 1)[0]
    examples = json.loads(example_json)
    assert len(examples) == 3
    assert all(item["original_text"] and item["final_text"] for item in examples)
