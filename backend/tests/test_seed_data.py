from sqlalchemy import func, select

from app.models import FormalMeme, RunRecord
from app.seed_data import CURATED_EXAMPLES


EXPECTED_TITLES = {
    "不在沉默中爆发，就在沉默中凿agu",
    "我负责赚钱养家，你负责凿agu",
    "凡事不要慌，先凿agu再说",
    "生活不止眼前的苟且，还有凿agu",
    "agu，真可怜，又被他们凿了吧",
}


async def test_curated_examples_are_stored_as_ordinary_successful_runs(
    repository, tmp_path,
):
    inserted = await repository.seed_completed_runs(
        CURATED_EXAMPLES,
        tmp_path / "runs",
    )

    assert inserted == 5
    assert set(await repository.list_formal_titles()) == EXPECTED_TITLES
    examples = await repository.sample_dynamic_examples(10)
    assert len(examples) == 5
    assert all(row.dynamic_example_eligible for row in examples)
    assert all(row.evaluation_status == "PASSED" for row in examples)

    for meme in examples:
        run = await repository.get_run(meme.source_run_id)
        assert run is not None
        assert run.mode in {"AUTO", "MANUAL_SEED"}
        assert run.status == "WAITING_HUMAN_EVALUATION"
        assert run.formal_meme_id == meme.id
        assert run.result_json["final_state"] == "WAITING_HUMAN_EVALUATION"
        assert run.result_json["stop_node"] == "H02"


async def test_curated_example_seeding_is_idempotent(repository, tmp_path):
    await repository.seed_completed_runs(CURATED_EXAMPLES, tmp_path / "runs")
    inserted_again = await repository.seed_completed_runs(
        CURATED_EXAMPLES,
        tmp_path / "runs",
    )

    async with repository.session() as session:
        run_count = await session.scalar(select(func.count()).select_from(RunRecord))
        meme_count = await session.scalar(select(func.count()).select_from(FormalMeme))
    assert inserted_again == 0
    assert run_count == 5
    assert meme_count == 5


async def test_curated_long_example_keeps_complete_original_and_final_text(
    repository, tmp_path,
):
    await repository.seed_completed_runs(CURATED_EXAMPLES, tmp_path / "runs")

    examples = await repository.sample_dynamic_examples(10)
    long_example = next(
        row for row in examples if row.final_title == "agu，真可怜，又被他们凿了吧"
    )
    assert long_example.original_text.startswith(
        "凯亚尔，真可怜，又被她们欺负了吧，你应该清楚"
    )
    assert long_example.original_text.endswith("明天会给你更多的爱。")
    assert long_example.final_text.startswith(
        "agu，真可怜，又被他们凿了吧。你应该清楚"
    )
    assert long_example.final_text.endswith("还有一把更小的凿子。")
