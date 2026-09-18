from datetime import UTC, datetime

from sqlalchemy import select

from app.models import FormalMeme


VALID_RESULT = {
    "final_state": "WAITING_HUMAN_EVALUATION",
    "stop_node": "H02",
    "complete_reference": {
        "title": "何以解忧",
        "complete_reference_text": "何以解忧？唯有杜康。",
    },
    "final_draft": {
        "title": "何以解忧？唯有凿agu。",
        "text": "何以解忧？唯有凿agu。",
    },
}


async def test_success_transaction_creates_formal_meme_and_updates_run(repository):
    run = await repository.create_run("AUTO", None, "/tmp/run")

    meme = await repository.complete_success(
        run.id,
        result=VALID_RESULT,
        usage={
            "input_tokens": 10,
            "cached_input_tokens": 8,
            "output_tokens": 2,
            "reasoning_tokens": 1,
        },
        duration_seconds=3,
        exit_code=0,
    )

    assert meme.dynamic_example_eligible is False
    assert meme.evaluation_status == "PENDING"
    stored = await repository.get_run(run.id)
    assert stored is not None
    assert stored.status == "WAITING_HUMAN_EVALUATION"
    assert stored.formal_meme_id == meme.id
    assert stored.result_json == VALID_RESULT
    assert stored.input_tokens == 10


async def test_failure_does_not_create_formal_meme(repository):
    run = await repository.create_run("MANUAL_SEED", "种子", "/tmp/run")

    await repository.complete_failure(
        run.id,
        error_code="SKILL_STOPPED_WITHOUT_RESULT",
        error_message="evidence insufficient",
        stop_reason="T09 INSUFFICIENT",
        duration_seconds=7,
        exit_code=0,
    )

    stored = await repository.get_run(run.id)
    assert stored is not None
    assert stored.status == "FAILED"
    assert stored.error_code == "SKILL_STOPPED_WITHOUT_RESULT"
    assert stored.skill_stop_reason == "T09 INSUFFICIENT"
    assert await repository.get_formal_meme_by_run(run.id) is None


async def test_logs_keep_run_local_sequence(repository):
    run = await repository.create_run("AUTO", None, "/tmp/run")

    await repository.append_log(
        run.id, 2, "STDERR", None, None, "warning", datetime.now(UTC),
    )
    await repository.append_log(
        run.id, 1, "STDOUT", "thread.started", {"type": "thread.started"}, None,
        datetime.now(UTC),
    )

    logs = await repository.list_logs(run.id)
    assert [row.sequence for row in logs] == [1, 2]
    assert logs[0].payload_json == {"type": "thread.started"}
    assert logs[1].raw_text == "warning"


async def test_dynamic_examples_only_include_eligible_records(repository):
    first = await repository.create_run("AUTO", None, "/tmp/one")
    second = await repository.create_run("AUTO", None, "/tmp/two")
    first_meme = await repository.complete_success(
        first.id, VALID_RESULT, {}, 1, 0,
    )
    await repository.complete_success(
        second.id,
        {
            **VALID_RESULT,
            "complete_reference": {
                "title": "原梗二",
                "complete_reference_text": "原文二",
            },
            "final_draft": {"title": "成品二", "text": "成品二"},
        },
        {}, 1, 0,
    )
    async with repository.session() as session, session.begin():
        stored = await session.get(FormalMeme, first_meme.id)
        assert stored is not None
        stored.dynamic_example_eligible = True
        stored.evaluation_status = "PASSED"

    examples = await repository.sample_dynamic_examples(3)

    assert [item.id for item in examples] == [first_meme.id]
    assert await repository.list_formal_titles() == ["何以解忧？唯有凿agu。", "成品二"]


async def test_source_run_is_unique(repository):
    run = await repository.create_run("AUTO", None, "/tmp/run")
    await repository.complete_success(run.id, VALID_RESULT, {}, 1, 0)

    async with repository.session() as session:
        rows = (await session.execute(
            select(FormalMeme).where(FormalMeme.source_run_id == run.id),
        )).scalars().all()

    assert len(rows) == 1
