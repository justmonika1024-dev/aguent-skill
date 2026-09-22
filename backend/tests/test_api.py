import json
from datetime import UTC, datetime
from pathlib import Path

import anyio
import pytest
from httpx import ASGITransport, AsyncClient

from app.api import create_app
from app.config import Settings
from app.runners.base import RunnerResult
from tests.fakes import FakeRunner, VALID_RESULT


def make_settings(tmp_path: Path) -> Settings:
    skill = tmp_path / "source-skill"
    (skill / "scripts").mkdir(parents=True)
    (skill / "SKILL.md").write_text("# fixture skill\n", encoding="utf-8")
    (skill / "scripts/compact_round_runner.py").write_text("pass\n", encoding="utf-8")
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


async def test_run_status_returns_not_found_for_unknown_run(client):
    http, _ = client

    response = await http.get(
        "/api/runs/00000000-0000-0000-0000-000000000000",
    )

    assert response.status_code == 404
    assert response.json() == {
        "error": {"code": "RUN_NOT_FOUND", "message": "run was not found"},
    }


async def test_running_status_returns_latest_progress_artifacts(tmp_path):
    runner = FakeRunner(VALID_RESULT, blocked=True)
    app = create_app(make_settings(tmp_path), runner)
    async with app.router.lifespan_context(app):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test",
        ) as http:
            created = await http.post("/api/runs", json={"mode": "AUTO"})
            await runner.started.wait()
            run_id = created.json()["run_id"]
            workdir = runner.calls[0][1]
            (workdir / "progress.json").write_text(
                json.dumps(
                    {
                        "latest_activity": "模板已经收敛，准备生成候选。",
                        "original_meme": {
                            "title": "何以解忧",
                            "text": "何以解忧？唯有杜康。",
                        },
                        "template": "何以{S1}？唯有{S2}。",
                        "formal_meme": None,
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            await app.state.repository.append_log(
                run_id,
                2,
                "STDOUT",
                "item.completed",
                {
                    "type": "item.completed",
                    "item": {
                        "type": "agent_message",
                        "text": "模板已确认，正在生成正式梗候选。",
                    },
                },
                None,
            )

            response = await http.get(f"/api/runs/{run_id}")
            runner.release.set()
            await app.state.run_service.wait_for_idle()

            assert response.status_code == 200
            payload = response.json()
            assert payload["run_id"] == run_id
            assert payload["mode"] == "AUTO"
            assert payload["status"] == "RUNNING"
            assert payload["elapsed_seconds"] >= 0
            assert payload["latest_activity"] == "模板已确认，正在生成正式梗候选。"
            assert payload["original_meme"] == {
                "title": "何以解忧",
                "text": "何以解忧？唯有杜康。",
            }
            assert payload["template"] == "何以{S1}？唯有{S2}。"
            assert payload["formal_meme"] is None
            assert payload["token_usage"] == {
                "input_tokens": 0,
                "cached_input_tokens": 0,
                "output_tokens": 0,
                "reasoning_tokens": 0,
                "total_tokens": 0,
                "finalized": False,
            }
            assert payload["error"] is None



async def test_completed_status_returns_terminal_result_and_exact_usage(client):
    http, app = client
    created = await http.post("/api/runs", json={"mode": "AUTO"})
    await app.state.run_service.wait_for_idle()
    run_id = created.json()["run_id"]

    response = await http.get(f"/api/runs/{run_id}")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "WAITING_HUMAN_EVALUATION"
    assert payload["elapsed_seconds"] == 2
    assert payload["finished_at"] is not None
    assert payload["latest_activity"] == "任务已到达人工评价阶段。"
    assert payload["original_meme"] == {
        "title": "何以解忧",
        "text": "何以解忧？唯有杜康。",
    }
    assert payload["template"] == "何以{S1}？唯有{S2}。"
    assert payload["formal_meme"] == {
        "title": "何以解忧？唯有凿agu。",
        "text": "何以解忧？唯有凿agu。",
    }
    assert payload["token_usage"] == {
        "input_tokens": 10,
        "cached_input_tokens": 8,
        "output_tokens": 2,
        "reasoning_tokens": 1,
        "total_tokens": 12,
        "finalized": True,
    }
    assert payload["error"] is None


class UsageThenBlockedRunner:
    def __init__(self) -> None:
        self.usage_reported = anyio.Event()
        self.release = anyio.Event()

    async def run(self, prompt, workdir: Path, log_sink):
        event = {
            "type": "turn.completed",
            "usage": {
                "input_tokens": 21,
                "cached_input_tokens": 13,
                "output_tokens": 5,
                "reasoning_output_tokens": 2,
            },
        }
        await log_sink("STDOUT", "turn.completed", event, None)
        self.usage_reported.set()
        await self.release.wait()
        (workdir / "run-result.json").write_text(
            json.dumps(VALID_RESULT, ensure_ascii=False), encoding="utf-8",
        )
        return RunnerResult(exit_code=0, duration_seconds=1, events=[event])


class CompactProgressRunner:
    def __init__(self) -> None:
        self.reported = anyio.Event()
        self.release = anyio.Event()

    async def run(self, invocation, workdir: Path, log_sink):
        handoff = workdir / "search-handoff"
        handoff.mkdir()
        (handoff / "boundary-result.json").write_text(
            json.dumps(
                {
                    "status": "VERIFIED",
                    "hook_text": "何以解忧",
                    "complete_reference_text": "何以解忧？唯有杜康。",
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        event = {
            "type": "compact.stage.started",
            "stage": "VARIANTS_01",
            "message": "正在执行精简阶段 VARIANTS_01",
        }
        await log_sink("STDOUT", event["type"], event, None)
        self.reported.set()
        await self.release.wait()
        (workdir / "run-result.json").write_text(
            json.dumps(VALID_RESULT, ensure_ascii=False),
            encoding="utf-8",
        )
        return RunnerResult(exit_code=0, duration_seconds=1, events=[])


async def test_running_compact_stage_reports_activity_and_verified_original(tmp_path):
    runner = CompactProgressRunner()
    app = create_app(make_settings(tmp_path), runner)
    async with app.router.lifespan_context(app):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test",
        ) as http:
            created = await http.post("/api/runs", json={"mode": "AUTO"})
            await runner.reported.wait()

            response = await http.get(f"/api/runs/{created.json()['run_id']}")
            runner.release.set()
            await app.state.run_service.wait_for_idle()

    payload = response.json()
    assert payload["status"] == "RUNNING"
    assert payload["latest_activity"] == "正在执行精简阶段 VARIANTS_01"
    assert payload["original_meme"] == {
        "title": "何以解忧",
        "text": "何以解忧？唯有杜康。",
    }


async def test_running_status_exposes_latest_reported_usage(tmp_path):
    runner = UsageThenBlockedRunner()
    app = create_app(make_settings(tmp_path), runner)
    async with app.router.lifespan_context(app):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test",
        ) as http:
            created = await http.post("/api/runs", json={"mode": "AUTO"})
            await runner.usage_reported.wait()

            response = await http.get(f"/api/runs/{created.json()['run_id']}")
            runner.release.set()
            await app.state.run_service.wait_for_idle()

            assert response.json()["status"] == "RUNNING"
            assert response.json()["token_usage"] == {
                "input_tokens": 21,
                "cached_input_tokens": 13,
                "output_tokens": 5,
                "reasoning_tokens": 2,
                "total_tokens": 26,
                "finalized": False,
            }


async def test_failed_status_returns_error_and_partial_progress(tmp_path):
    app = create_app(make_settings(tmp_path), FakeRunner(None, exit_code=7))
    async with app.router.lifespan_context(app):
        run = await app.state.repository.create_run(
            "AUTO", None, str(tmp_path / "failed-run"),
        )
        await app.state.repository.mark_running(run.id, datetime.now(UTC))
        await app.state.repository.complete_failure(
            run.id,
            "CLI_EXIT_NON_ZERO",
            "Codex CLI exited with status 7",
            "搜索提供方不可用",
            9,
            7,
        )
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test",
        ) as http:
            response = await http.get(f"/api/runs/{run.id}")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "FAILED"
    assert payload["elapsed_seconds"] == 9
    assert payload["token_usage"]["finalized"] is True
    assert payload["original_meme"] is None
    assert payload["template"] is None
    assert payload["formal_meme"] is None
    assert payload["latest_activity"] == "任务执行失败。"
    assert payload["error"] == {
        "code": "CLI_EXIT_NON_ZERO",
        "message": "Codex CLI exited with status 7",
    }
    assert payload["stop_reason"] == "搜索提供方不可用"


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


async def test_unplanned_read_endpoints_are_not_exposed(client):
    http, _ = client

    for path in ("/", "/api/runs", "/api/logs"):
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


async def test_startup_rejects_skill_without_compact_orchestrator(tmp_path):
    skill = tmp_path / "source-skill"
    skill.mkdir()
    (skill / "SKILL.md").write_text("# fixture skill\n", encoding="utf-8")
    settings = Settings(
        database_url=f"sqlite+aiosqlite:///{tmp_path / 'runner.db'}",
        run_root=tmp_path / "runs",
        skill_path=skill,
    )
    app = create_app(settings)

    with pytest.raises(RuntimeError, match="compact_round_runner.py"):
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

    invocation = runner.calls[0][0]
    examples = list(invocation.dynamic_examples)
    assert len(examples) == 3
    assert all(item["original_text"] and item["final_text"] for item in examples)
    assert all(item["score"] == 0 for item in examples)


async def test_evaluation_sets_unbounded_overall_score_and_enables_example(client):
    http, app = client
    created = await http.post(
        "/api/runs", json={"mode": "MANUAL_SEED", "seed_text": "人工原梗"},
    )
    await app.state.run_service.wait_for_idle()
    run_id = created.json()["run_id"]

    score = 10**100
    response = await http.post(
        f"/api/runs/{run_id}/evaluation", json={"score": score},
    )

    assert response.status_code == 200
    assert response.json() == {
        "run_id": run_id,
        "score": score,
        "evaluation_status": "SCORED",
        "dynamic_example_eligible": True,
    }
    meme = await app.state.repository.get_formal_meme_by_run(run_id)
    assert meme is not None
    assert meme.score == score
    assert meme.evaluation_json == {"score": score}


async def test_repeated_evaluation_overwrites_score(client):
    http, app = client
    created = await http.post("/api/runs", json={"mode": "AUTO"})
    await app.state.run_service.wait_for_idle()
    run_id = created.json()["run_id"]

    first = await http.post(f"/api/runs/{run_id}/evaluation", json={"score": 12})
    second = await http.post(f"/api/runs/{run_id}/evaluation", json={"score": 3})

    assert first.status_code == 200
    assert second.status_code == 200
    assert second.json()["score"] == 3
    meme = await app.state.repository.get_formal_meme_by_run(run_id)
    assert meme is not None and meme.score == 3


@pytest.mark.parametrize("score", [-1, 1.5, "12", None])
async def test_evaluation_rejects_invalid_score(client, score):
    http, _ = client

    response = await http.post(
        "/api/runs/not-a-run/evaluation", json={"score": score},
    )

    assert response.status_code == 422


async def test_evaluation_returns_not_found_for_unknown_run(client):
    http, _ = client

    response = await http.post(
        "/api/runs/00000000-0000-0000-0000-000000000000/evaluation",
        json={"score": 1},
    )

    assert response.status_code == 404
    assert response.json() == {
        "error": {"code": "RUN_NOT_FOUND", "message": "run was not found"},
    }


async def test_evaluation_rejects_run_without_formal_meme(client):
    http, app = client
    run = await app.state.repository.create_run("AUTO", None, "/tmp/incomplete")

    response = await http.post(
        f"/api/runs/{run.id}/evaluation", json={"score": 1},
    )

    assert response.status_code == 409
    assert response.json() == {
        "error": {
            "code": "FORMAL_MEME_NOT_READY",
            "message": "run has no formal meme to evaluate",
        },
    }


async def test_formal_memes_are_paginated_newest_first(client):
    http, _ = client

    first = await http.get("/api/formal-memes", params={"page": 1, "page_size": 2})
    second = await http.get("/api/formal-memes", params={"page": 2, "page_size": 2})

    assert first.status_code == 200
    assert first.json()["pagination"] == {
        "page": 1,
        "page_size": 2,
        "total": 5,
        "total_pages": 3,
    }
    assert second.json()["pagination"]["page"] == 2
    first_items = first.json()["items"]
    second_items = second.json()["items"]
    assert [item["final_title"] for item in first_items] == [
        "agu，真可怜，又被他们凿了吧",
        "生活不止眼前的苟且，还有凿agu",
    ]
    assert {item["id"] for item in first_items}.isdisjoint(
        item["id"] for item in second_items
    )
    assert set(first_items[0]) == {
        "id",
        "source_run_id",
        "original_title",
        "original_text",
        "final_title",
        "final_text",
        "score",
        "evaluation_status",
        "dynamic_example_eligible",
        "created_at",
    }


async def test_formal_memes_out_of_range_page_is_empty(client):
    http, _ = client

    response = await http.get(
        "/api/formal-memes", params={"page": 99, "page_size": 2},
    )

    assert response.status_code == 200
    assert response.json() == {
        "items": [],
        "pagination": {
            "page": 99,
            "page_size": 2,
            "total": 5,
            "total_pages": 3,
        },
    }


@pytest.mark.parametrize(
    "params",
    [
        {"page": 0},
        {"page_size": 0},
        {"page_size": 101},
        {"page": "one"},
    ],
)
async def test_formal_memes_reject_invalid_pagination(client, params):
    http, _ = client

    response = await http.get("/api/formal-memes", params=params)

    assert response.status_code == 422
