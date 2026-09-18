import json

import pytest

from app.result_parser import ResultError, extract_usage, parse_run_result


def write_result(tmp_path, payload):
    (tmp_path / "run-result.json").write_text(
        json.dumps(payload, ensure_ascii=False), encoding="utf-8",
    )


def test_missing_result_file_is_rejected(tmp_path):
    with pytest.raises(ResultError) as raised:
        parse_run_result(tmp_path)
    assert raised.value.code == "OUTPUT_MISSING"


def test_malformed_result_file_is_rejected(tmp_path):
    (tmp_path / "run-result.json").write_text("{", encoding="utf-8")
    with pytest.raises(ResultError) as raised:
        parse_run_result(tmp_path)
    assert raised.value.code == "OUTPUT_INVALID"


def test_non_h02_result_preserves_skill_stop_reason(tmp_path):
    write_result(tmp_path, {
        "final_state": "STOPPED_INSUFFICIENT_EVIDENCE",
        "stop_node": "T09",
        "stop_reason": "strict variants insufficient",
    })
    with pytest.raises(ResultError) as raised:
        parse_run_result(tmp_path)
    assert raised.value.code == "SKILL_STOPPED_WITHOUT_RESULT"
    assert raised.value.stop_reason == "strict variants insufficient"


@pytest.mark.parametrize("field", ["complete_reference", "final_draft"])
def test_empty_required_text_is_rejected(tmp_path, field):
    payload = {
        "final_state": "WAITING_HUMAN_EVALUATION",
        "stop_node": "H02",
        "complete_reference": {"complete_reference_text": "完整原梗"},
        "final_draft": {"text": "正式梗"},
    }
    payload[field] = {}
    write_result(tmp_path, payload)
    with pytest.raises(ResultError) as raised:
        parse_run_result(tmp_path)
    assert raised.value.code == "OUTPUT_INVALID"


def test_top_level_h02_result_is_normalized(tmp_path):
    payload = {
        "final_state": "WAITING_HUMAN_EVALUATION",
        "stop_node": "H02",
        "complete_reference": {
            "title": "原梗标题",
            "complete_reference_text": "完整原梗",
        },
        "final_draft": {"title": "正式标题", "text": "正式梗"},
    }
    write_result(tmp_path, payload)

    parsed = parse_run_result(tmp_path)

    assert parsed.original_title == "原梗标题"
    assert parsed.original_text == "完整原梗"
    assert parsed.final_title == "正式标题"
    assert parsed.final_text == "正式梗"
    assert parsed.raw == payload


def test_node_artifacts_are_supported(tmp_path):
    write_result(tmp_path, {
        "final_state": "WAITING_HUMAN_EVALUATION",
        "stop_node": "H02",
        "nodes": [
            {
                "node_key": "O05",
                "artifact": {"complete_reference": {
                    "complete_reference_text": "节点原梗",
                    "hook_text": "节点标题",
                }},
            },
            {
                "node_key": "G06",
                "artifact": {"title": "节点正式标题", "text": "节点正式梗"},
            },
        ],
    })

    parsed = parse_run_result(tmp_path)

    assert parsed.original_title == "节点标题"
    assert parsed.original_text == "节点原梗"
    assert parsed.final_title == "节点正式标题"
    assert parsed.final_text == "节点正式梗"


def test_extract_usage_uses_last_completed_turn():
    events = [
        {"type": "turn.completed", "usage": {"input_tokens": 1}},
        {"type": "agent_message", "text": "x"},
        {"type": "turn.completed", "usage": {
            "input_tokens": 10,
            "cached_input_tokens": 8,
            "output_tokens": 2,
            "reasoning_output_tokens": 1,
        }},
    ]

    assert extract_usage(events) == {
        "input_tokens": 10,
        "cached_input_tokens": 8,
        "output_tokens": 2,
        "reasoning_tokens": 1,
    }
