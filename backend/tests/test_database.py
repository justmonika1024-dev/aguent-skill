from datetime import UTC, datetime
import sqlite3

from sqlalchemy import event, select

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
    assert meme.score == 0
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
        stored.score = 27

    examples = await repository.sample_dynamic_examples(3)

    assert [item.id for item in examples] == [first_meme.id]
    assert examples[0].score == 27
    assert await repository.list_formal_titles() == ["何以解忧？唯有凿agu。", "成品二"]


async def test_formal_meme_page_uses_one_database_snapshot(repository):
    run = await repository.create_run("AUTO", None, "/tmp/first")
    first = await repository.complete_success(run.id, VALID_RESULT, {}, 1, 0)
    database = repository.engine.url.database
    assert database is not None
    with sqlite3.connect(database) as connection:
        connection.execute("PRAGMA journal_mode=WAL")

    inserted_during_query = False

    def insert_after_count(
        connection, cursor, statement, parameters, context, executemany,
    ):
        nonlocal inserted_during_query
        normalized = " ".join(statement.lower().split())
        if inserted_during_query or "count(" not in normalized:
            return
        inserted_during_query = True
        with sqlite3.connect(database) as writer:
            writer.execute(
                """
                INSERT INTO formal_memes (
                    id, source_run_id, original_title, original_text,
                    final_title, final_text, evaluation_status, evaluation_json,
                    score, dynamic_example_eligible, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    "concurrent-meme", "concurrent-run", "并发原题", "并发原文",
                    "并发成品题", "并发成品", "PENDING", None, "0", 0,
                    "2026-09-20 12:00:00",
                ),
            )

    event.listen(repository.engine.sync_engine, "after_cursor_execute", insert_after_count)
    try:
        items, total = await repository.list_formal_memes_page(page=1, page_size=100)
    finally:
        event.remove(
            repository.engine.sync_engine,
            "after_cursor_execute",
            insert_after_count,
        )

    assert inserted_during_query is True
    assert total == len(items)
    assert [item.id for item in items] == [first.id]


async def test_existing_sqlite_database_gets_score_column(tmp_path):
    database = tmp_path / "legacy.db"
    with sqlite3.connect(database) as connection:
        connection.execute("""
            CREATE TABLE formal_memes (
                id VARCHAR(36) PRIMARY KEY,
                source_run_id VARCHAR(36) NOT NULL,
                original_title TEXT NOT NULL,
                original_text TEXT NOT NULL,
                final_title TEXT NOT NULL,
                final_text TEXT NOT NULL,
                evaluation_status VARCHAR(32) NOT NULL,
                evaluation_json JSON,
                dynamic_example_eligible BOOLEAN NOT NULL,
                created_at DATETIME NOT NULL
            )
        """)
        connection.execute(
            """INSERT INTO formal_memes VALUES (
                'legacy-meme', 'legacy-run', '原题', '原文', '成品题', '成品',
                'PASSED', NULL, 1, '2026-09-01 00:00:00'
            )""",
        )

    from app.database import SQLiteRepository
    legacy = SQLiteRepository(f"sqlite+aiosqlite:///{database}")
    await legacy.init()
    async with legacy.session() as session:
        stored = await session.get(FormalMeme, "legacy-meme")
        assert stored is not None
        assert stored.final_text == "成品"
        assert stored.dynamic_example_eligible is True
        assert stored.score == 0
    await legacy.dispose()

    with sqlite3.connect(database) as connection:
        columns = {
            row[1]: row for row in connection.execute("PRAGMA table_info(formal_memes)")
        }
    assert columns["score"][2] == "TEXT"
    assert columns["score"][4].strip("'") == "0"


async def test_interim_integer_score_column_is_migrated_without_data_loss(tmp_path):
    database = tmp_path / "integer-score.db"
    with sqlite3.connect(database) as connection:
        connection.execute("""
            CREATE TABLE formal_memes (
                id VARCHAR(36) PRIMARY KEY,
                source_run_id VARCHAR(36) NOT NULL,
                original_title TEXT NOT NULL,
                original_text TEXT NOT NULL,
                final_title TEXT NOT NULL,
                final_text TEXT NOT NULL,
                evaluation_status VARCHAR(32) NOT NULL,
                evaluation_json JSON,
                score INTEGER NOT NULL DEFAULT 0,
                dynamic_example_eligible BOOLEAN NOT NULL,
                created_at DATETIME NOT NULL
            )
        """)
        connection.execute(
            """INSERT INTO formal_memes VALUES (
                'integer-meme', 'integer-run', '原题', '原文', '成品题', '成品',
                'SCORED', '{"score": 27}', 27, 1, '2026-09-01 00:00:00'
            )""",
        )

    from app.database import SQLiteRepository
    legacy = SQLiteRepository(f"sqlite+aiosqlite:///{database}")
    await legacy.init()
    async with legacy.session() as session:
        stored = await session.get(FormalMeme, "integer-meme")
        assert stored is not None and stored.score == 27
    await legacy.dispose()

    with sqlite3.connect(database) as connection:
        columns = {
            row[1]: row for row in connection.execute("PRAGMA table_info(formal_memes)")
        }
    assert columns["score"][2] == "TEXT"


async def test_source_run_is_unique(repository):
    run = await repository.create_run("AUTO", None, "/tmp/run")
    await repository.complete_success(run.id, VALID_RESULT, {}, 1, 0)

    async with repository.session() as session:
        rows = (await session.execute(
            select(FormalMeme).where(FormalMeme.source_run_id == run.id),
        )).scalars().all()

    assert len(rows) == 1
