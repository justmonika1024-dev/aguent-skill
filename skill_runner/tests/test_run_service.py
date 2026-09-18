from pathlib import Path

import pytest

from app.config import Settings
from app.models import FormalMeme
from app.run_service import ActiveRunExists, RunService
from app.schemas import RunCreate
from tests.fakes import FakeRunner, VALID_RESULT


def make_settings(tmp_path: Path) -> Settings:
    skill = tmp_path / "source-skill"
    skill.mkdir()
    (skill / "SKILL.md").write_text("# fixture skill\n", encoding="utf-8")
    return Settings(
        database_url=f"sqlite+aiosqlite:///{tmp_path / 'runner.db'}",
        run_root=tmp_path / "runs",
        skill_path=skill,
        dynamic_example_count=3,
        codex_command="codex",
    )


async def test_start_prepares_isolated_workdir_and_rejects_parallel_run(repository, tmp_path):
    runner = FakeRunner(VALID_RESULT, blocked=True)
    settings = make_settings(tmp_path)
    service = RunService(settings, repository, runner)

    run = await service.start(RunCreate(mode="MANUAL_SEED", seed_text="种子"))
    await runner.started.wait()

    assert run.status == "PENDING"
    workdir = Path(run.workdir)
    assert workdir == settings.run_root / run.id
    assert (workdir / ".agents/skills/zao-agugent-supervisor/SKILL.md").is_file()
    assert (workdir / ".git").is_dir()
    assert (workdir / "prompt.md").is_file()
    with pytest.raises(ActiveRunExists):
        await service.start(RunCreate(mode="AUTO"))

    runner.release.set()
    await service.wait_for_idle()
    assert (await repository.get_run(run.id)).status == "WAITING_HUMAN_EVALUATION"


async def test_h02_result_is_stored_and_lock_is_released(repository, tmp_path):
    service = RunService(make_settings(tmp_path), repository, FakeRunner(VALID_RESULT))

    first = await service.start(RunCreate(mode="AUTO"))
    await service.wait_for_idle()

    stored = await repository.get_run(first.id)
    meme = await repository.get_formal_meme_by_run(first.id)
    assert stored is not None and stored.status == "WAITING_HUMAN_EVALUATION"
    assert meme is not None and meme.final_text == "何以解忧？唯有凿agu。"
    second = await service.start(RunCreate(mode="MANUAL_SEED", seed_text="第二轮"))
    await service.wait_for_idle()
    assert (await repository.get_run(second.id)).status == "WAITING_HUMAN_EVALUATION"


@pytest.mark.parametrize(
    ("runner", "expected_code"),
    [
        (FakeRunner(VALID_RESULT, exit_code=7), "CLI_EXIT_NON_ZERO"),
        (FakeRunner({
            "final_state": "STOPPED_INSUFFICIENT_EVIDENCE",
            "stop_node": "T09",
            "stop_reason": "no variants",
        }), "SKILL_STOPPED_WITHOUT_RESULT"),
        (FakeRunner(None), "OUTPUT_MISSING"),
    ],
)
async def test_failure_paths_do_not_store_formal_meme(
    repository, tmp_path, runner, expected_code,
):
    service = RunService(make_settings(tmp_path), repository, runner)
    run = await service.start(RunCreate(mode="AUTO"))

    await service.wait_for_idle()

    stored = await repository.get_run(run.id)
    assert stored is not None and stored.status == "FAILED"
    assert stored.error_code == expected_code
    assert await repository.get_formal_meme_by_run(run.id) is None


async def test_auto_prompt_uses_only_eligible_dynamic_examples(repository, tmp_path):
    eligible_run = await repository.create_run("AUTO", None, "/tmp/eligible")
    ineligible_run = await repository.create_run("AUTO", None, "/tmp/ineligible")
    eligible = await repository.complete_success(
        eligible_run.id, VALID_RESULT, {}, 1, 0,
    )
    await repository.complete_success(
        ineligible_run.id,
        {
            **VALID_RESULT,
            "complete_reference": {
                "title": "不要注入的原梗",
                "complete_reference_text": "不要注入的原文",
            },
            "final_draft": {"title": "不要注入", "text": "不要注入"},
        },
        {}, 1, 0,
    )
    async with repository.session() as session, session.begin():
        row = await session.get(FormalMeme, eligible.id)
        row.dynamic_example_eligible = True
        row.evaluation_status = "PASSED"
    runner = FakeRunner(VALID_RESULT)
    service = RunService(make_settings(tmp_path), repository, runner)

    await service.start(RunCreate(mode="AUTO"))
    await service.wait_for_idle()

    prompt = runner.calls[0][0]
    assert "何以解忧？唯有杜康。" in prompt
    assert "何以解忧？唯有凿agu。" in prompt
    assert "不要注入的原文" not in prompt
    assert "不要注入" in prompt  # all formal titles are still injected for dedupe


async def test_logs_are_persisted_from_runner(repository, tmp_path):
    service = RunService(make_settings(tmp_path), repository, FakeRunner(VALID_RESULT))
    run = await service.start(RunCreate(mode="AUTO"))

    await service.wait_for_idle()

    logs = await repository.list_logs(run.id)
    assert [row.sequence for row in logs] == list(range(1, len(logs) + 1))
    assert any(row.stream == "STDOUT" and row.event_type == "turn.completed" for row in logs)
    assert any(row.stream == "STDERR" and row.raw_text == "fixture stderr" for row in logs)
    assert any(row.stream == "SYSTEM" for row in logs)
