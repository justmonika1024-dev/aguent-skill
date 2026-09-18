# Skill Runner API Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a standalone local FastAPI service whose single `POST /api/runs` endpoint starts a MANUAL_SEED or AUTO Codex CLI + Playwright Skill round, persists all logs to SQLite, and stores H02 results as formal memes.

**Architecture:** A process-local `RunService` owns the single-active-run lock and schedules one background task. `CodexCliRunner` streams subprocess stdout/stderr into a repository through a minimal `AgentRunner` protocol. The service does not reimplement Skill nodes: it builds the input prompt, invokes a fresh isolated CLI run, validates `run-result.json`, and transactionally persists the successful run and formal meme.

**Tech Stack:** Python 3.12, FastAPI, Pydantic 2, SQLAlchemy 2 Async, aiosqlite, pytest, pytest-asyncio, HTTPX, Codex CLI, Playwright MCP

**Spec:** `docs/superpowers/specs/2026-09-18-skill-runner-api-design.md`

## Global Constraints

- Create an independent `skill_runner/` package; do not modify or import the existing `backend/app/workflow` implementation.
- Expose only `POST /api/runs`; do not add health, status, log, evaluation, or formal-meme endpoints.
- Support exactly `MANUAL_SEED` and `AUTO`; MANUAL_SEED requires a nonblank seed and AUTO forbids a seed.
- Run at most one task per service process; H02 and FAILED both release the lock.
- Persist stdout, stderr, and system events in SQLite while the subprocess runs.
- Insert a formal meme only when the CLI exits zero and the machine result validates as H02.
- New formal memes start with `dynamic_example_eligible=false`; AUTO samples at most three eligible records.
- Keep run directories after completion and perform no crash recovery.
- Default automated tests must not call real Codex, Playwright, a model, or the network.

---

### Task 1: Standalone package, configuration, and SQLite repository

**Files:**
- Create: `skill_runner/pyproject.toml`
- Create: `skill_runner/app/__init__.py`
- Create: `skill_runner/app/config.py`
- Create: `skill_runner/app/models.py`
- Create: `skill_runner/app/database.py`
- Create: `skill_runner/tests/__init__.py`
- Create: `skill_runner/tests/conftest.py`
- Create: `skill_runner/tests/test_database.py`

**Interfaces:**
- Produces: `Settings`, `RunRecord`, `RunLog`, `FormalMeme`, `SQLiteRepository`.
- `SQLiteRepository.create_run(mode, seed_text, workdir) -> RunRecord`.
- `SQLiteRepository.mark_running(run_id, started_at) -> None`.
- `SQLiteRepository.append_log(run_id, sequence, stream, event_type, payload, raw_text) -> None`.
- `SQLiteRepository.sample_dynamic_examples(limit) -> list[FormalMeme]`.
- `SQLiteRepository.complete_success(run_id, result, usage, duration_seconds, exit_code) -> FormalMeme`.
- `SQLiteRepository.complete_failure(run_id, error_code, error_message, stop_reason, duration_seconds, exit_code) -> None`.

- [ ] **Step 1: Write failing repository tests**

Create tests that initialize a temporary SQLite database and assert:

```python
async def test_success_transaction_creates_formal_meme_and_updates_run(repository):
    run = await repository.create_run("AUTO", None, "/tmp/run")
    meme = await repository.complete_success(
        run.id,
        result={
            "final_state": "WAITING_HUMAN_EVALUATION",
            "stop_node": "H02",
            "complete_reference": {"title": "原梗", "complete_reference_text": "原文"},
            "final_draft": {"title": "正式梗", "text": "成品"},
        },
        usage={"input_tokens": 10, "cached_input_tokens": 8,
               "output_tokens": 2, "reasoning_tokens": 1},
        duration_seconds=3,
        exit_code=0,
    )
    assert meme.dynamic_example_eligible is False
    stored = await repository.get_run(run.id)
    assert stored.status == "WAITING_HUMAN_EVALUATION"
    assert stored.formal_meme_id == meme.id
```

Add tests for ordered log insertion, eligible-only random sampling, and failure completion without a formal meme.

- [ ] **Step 2: Run the repository tests and verify RED**

Run: `cd skill_runner && uv run pytest tests/test_database.py -q`

Expected: collection/import failure because `app.database` and models do not exist.

- [ ] **Step 3: Implement the minimal package and repository**

Define SQLAlchemy models exactly matching the spec. Use `async_sessionmaker`, `Base.metadata.create_all`, and one transaction in `complete_success`. Derive the formal-meme fields from the validated result dictionaries; do not add archive or workflow-node tables.

Define settings with these defaults:

```python
database_url = "sqlite+aiosqlite:///./data/skill-runner.db"
run_root = Path("./data/runs")
skill_path = Path("./.agents/skills/zao-agugent-supervisor")
dynamic_example_count = 3
codex_command = "codex"
```

- [ ] **Step 4: Run repository tests and verify GREEN**

Run: `cd skill_runner && uv run pytest tests/test_database.py -q`

Expected: all repository tests pass.

- [ ] **Step 5: Commit Task 1**

```bash
git add skill_runner
git commit -m "feat: add skill runner persistence"
```

### Task 2: Request schema, prompt builder, and result parser

**Files:**
- Create: `skill_runner/app/schemas.py`
- Create: `skill_runner/app/prompt_builder.py`
- Create: `skill_runner/app/result_parser.py`
- Create: `skill_runner/tests/test_prompt_builder.py`
- Create: `skill_runner/tests/test_result_parser.py`

**Interfaces:**
- Produces: `RunMode`, `RunCreate`, `RunAccepted`, `DynamicExample`, `ParsedRunResult`, `build_prompt`, `parse_run_result`, `extract_usage`.
- `build_prompt(request, formal_titles, dynamic_examples) -> str`.
- `parse_run_result(workdir) -> ParsedRunResult` raises `ResultError(code, message, stop_reason)`.
- `extract_usage(events) -> dict[str, int]` reads the last `turn.completed.usage` values.

- [ ] **Step 1: Write failing request and prompt tests**

Test Pydantic validation and exact prompt properties:

```python
def test_manual_seed_requires_nonblank_seed():
    with pytest.raises(ValidationError):
        RunCreate(mode="MANUAL_SEED", seed_text="   ")

def test_auto_forbids_seed():
    with pytest.raises(ValidationError):
        RunCreate(mode="AUTO", seed_text="x")

def test_auto_prompt_marks_dynamic_examples_as_non_evidence():
    prompt = build_prompt(
        RunCreate(mode="AUTO"),
        formal_titles=["已存在"],
        dynamic_examples=[DynamicExample(
            original_title="原梗", original_text="原文",
            final_title="正式梗", final_text="成品",
        )],
    )
    assert "只用于理解改编风格" in prompt
    assert "不能作为本轮网络证据" in prompt
    assert "run-result.json" in prompt
```

- [ ] **Step 2: Run prompt tests and verify RED**

Run: `cd skill_runner && uv run pytest tests/test_prompt_builder.py -q`

Expected: import failure because schemas and builder are absent.

- [ ] **Step 3: Implement request schemas and prompt builder**

Use a discriminating model validator for mode/seed constraints. Build one prompt template with mode-specific input. Include the formal title exclusion list, AUTO dynamic examples, required Skill/provider constraints, H02 stop rule, and fixed output filenames. Do not shell-escape or quote the prompt for command-line use because the runner writes it through stdin.

- [ ] **Step 4: Run prompt tests and verify GREEN**

Run: `cd skill_runner && uv run pytest tests/test_prompt_builder.py -q`

Expected: all prompt tests pass.

- [ ] **Step 5: Write failing result-parser tests**

Cover missing file, malformed JSON, non-H02 stop, missing original text, missing final text, and a valid result. Verify usage extraction from:

```json
{"type":"turn.completed","usage":{"input_tokens":10,"cached_input_tokens":8,"output_tokens":2,"reasoning_output_tokens":1}}
```

- [ ] **Step 6: Run result-parser tests and verify RED**

Run: `cd skill_runner && uv run pytest tests/test_result_parser.py -q`

Expected: import failure or missing function failure.

- [ ] **Step 7: Implement minimal result parsing**

Accept known field shapes used by the Skill records but normalize to:

```python
ParsedRunResult(
    raw=payload,
    original_title=str,
    original_text=str,
    final_title=str,
    final_text=str,
)
```

Return `SKILL_STOPPED_WITHOUT_RESULT` when a valid machine record reports a non-H02 state; use `OUTPUT_MISSING` and `OUTPUT_INVALID` for file and schema failures.

- [ ] **Step 8: Run parser and all Task 2 tests**

Run: `cd skill_runner && uv run pytest tests/test_prompt_builder.py tests/test_result_parser.py -q`

Expected: all Task 2 tests pass.

- [ ] **Step 9: Commit Task 2**

```bash
git add skill_runner/app/schemas.py skill_runner/app/prompt_builder.py \
  skill_runner/app/result_parser.py skill_runner/tests/test_prompt_builder.py \
  skill_runner/tests/test_result_parser.py
git commit -m "feat: build skill run prompts and parse results"
```

### Task 3: Codex CLI runner with incremental database logging

**Files:**
- Create: `skill_runner/app/runners/__init__.py`
- Create: `skill_runner/app/runners/base.py`
- Create: `skill_runner/app/runners/codex_cli.py`
- Create: `skill_runner/tests/test_codex_cli_runner.py`

**Interfaces:**
- Produces: `AgentRunner`, `RunnerResult`, `LogSink`, `CodexCliRunner`.
- `CodexCliRunner.run(prompt, workdir, log_sink) -> RunnerResult`.
- `LogSink(stream, event_type, payload, raw_text) -> Awaitable[None]`.

- [ ] **Step 1: Write a failing subprocess integration test**

Create an executable temporary Python fixture that reads stdin, writes one JSON event to stdout, one text line to stderr, writes a valid `run-result.json`, and exits zero. Assert the runner:

- passes the prompt through stdin;
- invokes a parameter array without a shell;
- records stdout and stderr through the sink;
- returns exit code and parsed event list;
- includes `--ephemeral`, `--disable memories`, `--approve-for-me`, `--json`, `-C`, and Playwright MCP overrides.

- [ ] **Step 2: Run runner tests and verify RED**

Run: `cd skill_runner && uv run pytest tests/test_codex_cli_runner.py -q`

Expected: import failure because runner modules are absent.

- [ ] **Step 3: Implement CodexCliRunner**

Use `asyncio.create_subprocess_exec` with `stdin`, `stdout`, and `stderr` pipes. Feed UTF-8 prompt bytes, consume both output streams concurrently, parse stdout JSONL when possible, and call the sink for every line. Measure duration with `time.monotonic`. Never use `shell=True`.

- [ ] **Step 4: Run runner tests and verify GREEN**

Run: `cd skill_runner && uv run pytest tests/test_codex_cli_runner.py -q`

Expected: all runner tests pass without invoking Codex or the network.

- [ ] **Step 5: Commit Task 3**

```bash
git add skill_runner/app/runners skill_runner/tests/test_codex_cli_runner.py
git commit -m "feat: execute codex cli skill runs"
```

### Task 4: Run service, isolated workspace preparation, and single API

**Files:**
- Create: `skill_runner/app/run_service.py`
- Create: `skill_runner/app/api.py`
- Create: `skill_runner/app/main.py`
- Create: `skill_runner/tests/fakes.py`
- Create: `skill_runner/tests/test_run_service.py`
- Create: `skill_runner/tests/test_api.py`

**Interfaces:**
- Produces: `RunService.start(request) -> RunRecord`, `create_app(settings, runner=None) -> FastAPI`.
- `RunService` owns one `asyncio.Lock` and a set containing the current background task.
- `POST /api/runs` returns HTTP 202 with `{run_id, status}`.

- [ ] **Step 1: Write failing RunService tests**

With a controllable Fake Runner, assert:

- start creates `RUN_ROOT/{run_id}` and returns PENDING;
- copied Skill contains `SKILL.md`;
- a minimal Git repository is initialized;
- a second start while the fake runner is blocked raises `ActiveRunExists`;
- runner completion at valid H02 persists the formal meme and releases the lock;
- runner failure or non-H02 output marks FAILED, creates no formal meme, and releases the lock;
- AUTO prompt includes only eligible examples and at most the configured count.

- [ ] **Step 2: Run RunService tests and verify RED**

Run: `cd skill_runner && uv run pytest tests/test_run_service.py -q`

Expected: import failure because `RunService` is absent.

- [ ] **Step 3: Implement RunService minimally**

Prepare the workdir, copy the Skill with `shutil.copytree`, initialize Git with `git init -q`, build the prompt, create a run row, and schedule `_execute`. Use repository logs for SYSTEM transitions. Parse the result only after exit zero. Always release the lock in `finally`.

- [ ] **Step 4: Run RunService tests and verify GREEN**

Run: `cd skill_runner && uv run pytest tests/test_run_service.py -q`

Expected: all service tests pass.

- [ ] **Step 5: Write failing API tests**

Use HTTPX ASGI transport and assert:

- valid MANUAL_SEED and AUTO return 202;
- missing manual seed, AUTO seed, invalid mode, and extra fields return 422;
- an active run returns 409 with `ACTIVE_RUN_EXISTS`;
- the app exposes no GET run/log/formal-meme endpoints.

- [ ] **Step 6: Run API tests and verify RED**

Run: `cd skill_runner && uv run pytest tests/test_api.py -q`

Expected: import failure or route-not-found failure because API code is absent.

- [ ] **Step 7: Implement the FastAPI app and sole route**

Create dependencies during the app lifespan, initialize SQLite, and wire the supplied or real runner. Map `ActiveRunExists` to HTTP 409 and request validation to FastAPI's standard 422. Do not add root or health routes.

- [ ] **Step 8: Run Task 4 and regression tests**

Run: `cd skill_runner && uv run pytest -q`

Expected: all tests pass.

- [ ] **Step 9: Commit Task 4**

```bash
git add skill_runner/app/run_service.py skill_runner/app/api.py \
  skill_runner/app/main.py skill_runner/tests/fakes.py \
  skill_runner/tests/test_run_service.py skill_runner/tests/test_api.py
git commit -m "feat: expose asynchronous skill run API"
```

### Task 5: Operator documentation and delivery verification

**Files:**
- Create: `skill_runner/.env.example`
- Create: `skill_runner/README.md`
- Create: `skill_runner/tests/test_delivery_contract.py`

**Interfaces:**
- Documents exact setup, start command, request examples, SQLite inspection commands, artifact directory, real-run prerequisites, and manual real test.

- [ ] **Step 1: Write a failing delivery-contract test**

Assert that `.env.example` contains all five required settings, README contains the sole route and both request modes, and OpenAPI has exactly one application route (`POST /api/runs`) after filtering documentation routes.

- [ ] **Step 2: Run delivery test and verify RED**

Run: `cd skill_runner && uv run pytest tests/test_delivery_contract.py -q`

Expected: failure because README and environment example are absent.

- [ ] **Step 3: Write minimal operator documentation**

Document:

```bash
cd skill_runner
uv sync
uv run uvicorn app.main:app --host 127.0.0.1 --port 8100
```

Include curl examples for both modes, SQL queries for runs/logs/formal memes, the single-worker requirement, current Codex login requirement, headed Playwright requirement, and the fact that default tests use a fake runner.

- [ ] **Step 4: Run the complete automated suite**

Run: `cd skill_runner && uv run pytest -q`

Expected: all tests pass with no real model or network calls.

- [ ] **Step 5: Run static delivery checks**

Run:

```bash
cd skill_runner
uv run python -m compileall -q app tests
uv run python -c "from app.main import app; assert any(r.path == '/api/runs' for r in app.routes)"
git diff --check
```

Expected: all commands exit zero.

- [ ] **Step 6: Run a local Fake Runner API smoke test**

Start the app through its test factory with a Fake Runner, submit one MANUAL_SEED request, wait for the background task, and query SQLite directly. Verify one H02 run, ordered logs, and one formal meme.

- [ ] **Step 7: Commit Task 5**

```bash
git add skill_runner/.env.example skill_runner/README.md \
  skill_runner/tests/test_delivery_contract.py
git commit -m "docs: document skill runner operation"
```

- [ ] **Step 8: Final review**

Review the diff against every acceptance criterion in the design. Confirm no existing backend/frontend files changed, no extra HTTP route was added, and no test contacted Codex, Playwright, a model, or the network.
