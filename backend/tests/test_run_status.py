import json
from datetime import UTC, datetime

from app.models import RunRecord
from app.run_status import _template, build_run_status


def test_long_form_rhythm_skeleton_is_exposed_as_human_readable_template():
    result = {
        "selected_route": "LONG_FORM",
        "long_form_plan": {
            "rhythm_skeleton": [
                {"order": 1, "function": "开场签到或心情声明"},
                {"order": 2, "function": "保留完整高辨识原句"},
                {"order": 3, "function": "追加用途转折并落到凿agu"},
            ]
        },
    }

    assert _template(result) == (
        "开场签到或心情声明 → 保留完整高辨识原句 → 追加用途转折并落到凿agu"
    )


def test_structured_template_is_exposed_from_direct_template_field():
    assert _template({"template": {"pattern": "一言不合就{ACTION_EVENT}"}}) == (
        "一言不合就{ACTION_EVENT}"
    )
    assert _template(
        {
            "template": {
                "rendering": "{project}{attribute}哪家强？中国山东找蓝翔。"
            }
        }
    ) == "{project}{attribute}哪家强？中国山东找蓝翔。"


async def test_unverified_search_boundary_is_not_exposed_as_confirmed_original(tmp_path):
    workdir = tmp_path / "run"
    handoff = workdir / "search-handoff"
    handoff.mkdir(parents=True)
    (handoff / "boundary-result.json").write_text(
        json.dumps(
            {
                "status": "NEEDS_MORE_EVIDENCE",
                "hook_text": "疑似标题",
                "complete_reference_text": "这只是尚未核验的候选文本。",
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    run = RunRecord(
        id="run-1",
        mode="AUTO",
        status="RUNNING",
        workdir=str(workdir),
        input_tokens=0,
        cached_input_tokens=0,
        output_tokens=0,
        reasoning_tokens=0,
        created_at=datetime.now(UTC),
    )

    status = await build_run_status(run, [])

    assert status.original_meme is None
