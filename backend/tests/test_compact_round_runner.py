import json
import sys
from pathlib import Path

from app.runners.base import RunInvocation
from app.runners.compact_round import CompactRoundRunner


async def test_runner_invokes_programmatic_orchestrator_with_structured_input(tmp_path):
    skill = tmp_path / "source-skill"
    (skill / "scripts").mkdir(parents=True)
    fixture = skill / "scripts/compact_round_runner.py"
    fixture.write_text(
        "import json, pathlib, sys\n"
        "pathlib.Path(sys.argv[sys.argv.index('--workdir') + 1], 'argv.json').write_text("
        "json.dumps(sys.argv[1:]), encoding='utf-8')\n",
        encoding="utf-8",
    )
    workdir = tmp_path / "run"
    workdir.mkdir()
    captured = []

    async def sink(stream, event_type, payload, raw_text):
        captured.append((stream, event_type, payload, raw_text))

    invocation = RunInvocation(
        mode="MANUAL_SEED",
        seed_text="种子 $(touch should-not-exist)",
        formal_titles=("标题一", "标题二"),
        dynamic_examples=(
            {
                "original_title": "原梗",
                "original_text": "原文",
                "final_title": "正式梗",
                "final_text": "正文",
                "score": 7,
            },
        ),
    )
    runner = CompactRoundRunner(
        skill_path=skill,
        codex_command="codex-test",
        python_command=sys.executable,
    )

    result = await runner.run(invocation, workdir, sink)

    assert result.exit_code == 0
    args = json.loads((workdir / "argv.json").read_text(encoding="utf-8"))
    assert args[args.index("--mode") + 1] == "MANUAL_SEED"
    assert args[args.index("--seed") + 1] == invocation.seed_text
    assert args[args.index("--workdir") + 1] == str(workdir.resolve())
    assert args[args.index("--skill-root") + 1] == str(skill.resolve())
    assert args[args.index("--codex-command") + 1] == "codex-test"
    assert [args[index + 1] for index, value in enumerate(args) if value == "--formal-title"] == [
        "标题一",
        "标题二",
    ]
    examples_path = Path(args[args.index("--dynamic-examples-json") + 1])
    assert json.loads(examples_path.read_text(encoding="utf-8")) == list(
        invocation.dynamic_examples,
    )
    assert not (workdir / "should-not-exist").exists()


async def test_runner_streams_compact_stage_events_and_stderr(tmp_path):
    skill = tmp_path / "source-skill"
    (skill / "scripts").mkdir(parents=True)
    fixture = skill / "scripts/compact_round_runner.py"
    fixture.write_text(
        "import json, sys\n"
        "print(json.dumps({'type': 'compact.stage.started', 'stage': 'BOUNDARY_01'}), flush=True)\n"
        "print(json.dumps({'type': 'compact.stage.completed', 'stage': 'BOUNDARY_01', "
        "'cumulative_usage': {'input_tokens': 120, 'cached_input_tokens': 90, "
        "'output_tokens': 12, 'reasoning_tokens': 4}}), flush=True)\n"
        "print('fixture warning', file=sys.stderr, flush=True)\n",
        encoding="utf-8",
    )
    workdir = tmp_path / "run"
    workdir.mkdir()
    captured = []

    async def sink(stream, event_type, payload, raw_text):
        captured.append((stream, event_type, payload, raw_text))

    runner = CompactRoundRunner(skill, "codex-test", python_command=sys.executable)
    result = await runner.run(
        RunInvocation(mode="AUTO"),
        workdir,
        sink,
    )

    assert result.exit_code == 0
    assert [event["type"] for event in result.events] == [
        "compact.stage.started",
        "compact.stage.completed",
    ]
    assert ("STDERR", None, None, "fixture warning") in captured
    assert any(event_type == "compact.stage.completed" for _, event_type, _, _ in captured)


async def test_runner_accepts_large_single_line_stage_event(tmp_path):
    skill = tmp_path / "source-skill"
    (skill / "scripts").mkdir(parents=True)
    fixture = skill / "scripts/compact_round_runner.py"
    fixture.write_text(
        "import json\n"
        "print(json.dumps({'type': 'compact.stage.completed', 'text': 'x' * 100_000}))\n",
        encoding="utf-8",
    )
    workdir = tmp_path / "run"
    workdir.mkdir()

    async def sink(*_):
        return None

    runner = CompactRoundRunner(skill, "codex-test", python_command=sys.executable)
    result = await runner.run(RunInvocation(mode="AUTO"), workdir, sink)

    assert len(result.events[0]["text"]) == 100_000
