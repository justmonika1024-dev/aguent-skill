import json
import sys

from app.runners.codex_cli import CodexCliRunner


async def test_runner_streams_logs_and_uses_safe_codex_arguments(tmp_path):
    fixture = tmp_path / "fake_codex.py"
    fixture.write_text(
        """
import json
import pathlib
import sys

pathlib.Path("stdin.txt").write_text(sys.stdin.read(), encoding="utf-8")
pathlib.Path("argv.json").write_text(json.dumps(sys.argv[1:]), encoding="utf-8")
print(json.dumps({"type": "thread.started", "thread_id": "t1"}), flush=True)
print("fixture warning", file=sys.stderr, flush=True)
""",
        encoding="utf-8",
    )
    captured = []

    async def sink(stream, event_type, payload, raw_text):
        captured.append({
            "stream": stream,
            "event_type": event_type,
            "payload": payload,
            "raw_text": raw_text,
        })

    prompt = "种子 $(touch should-not-exist)"
    runner = CodexCliRunner(command=[sys.executable, str(fixture)])

    result = await runner.run(prompt, tmp_path, sink)

    assert result.exit_code == 0
    assert result.duration_seconds >= 0
    assert result.events == [{"type": "thread.started", "thread_id": "t1"}]
    assert (tmp_path / "stdin.txt").read_text(encoding="utf-8") == prompt
    assert not (tmp_path / "should-not-exist").exists()
    args = json.loads((tmp_path / "argv.json").read_text(encoding="utf-8"))
    assert args[0] == "exec"
    assert "--ephemeral" in args
    assert "--disable" in args
    assert "memories" in args
    assert "--approve-for-me" in args
    assert "--json" in args
    assert "-C" in args
    assert str(tmp_path) in args
    assert any("mcp_servers.playwright.command" in value for value in args)
    assert any("@playwright/mcp@latest" in value for value in args)
    assert any(item["stream"] == "STDOUT" and item["event_type"] == "thread.started"
               for item in captured)
    assert any(item["stream"] == "STDERR" and item["raw_text"] == "fixture warning"
               for item in captured)


async def test_runner_preserves_non_json_stdout(tmp_path):
    fixture = tmp_path / "plain.py"
    fixture.write_text("print('plain output')\n", encoding="utf-8")
    captured = []

    async def sink(stream, event_type, payload, raw_text):
        captured.append((stream, event_type, payload, raw_text))

    runner = CodexCliRunner(command=[sys.executable, str(fixture)])
    result = await runner.run("x", tmp_path, sink)

    assert result.events == []
    assert ("STDOUT", None, None, "plain output") in captured
