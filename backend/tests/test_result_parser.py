import json

import pytest

from app.result_parser import (
    ResultError,
    extract_compact_metrics,
    extract_usage,
    parse_run_result,
)


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


def test_nested_stop_contract_from_supervisor_is_supported(tmp_path):
    payload = {
        "complete_reference": {
            "hook_text": "原梗标题",
            "complete_reference_text": "完整原梗",
        },
        "final_draft": {"title": "正式标题", "text": "正式梗"},
        "stop": {
            "node_key": "H02",
            "status": "WAITING_HUMAN_EVALUATION",
            "reason": "等待人工评价",
        },
    }
    write_result(tmp_path, payload)

    parsed = parse_run_result(tmp_path)

    assert parsed.original_title == "原梗标题"
    assert parsed.original_text == "完整原梗"
    assert parsed.final_title == "正式标题"
    assert parsed.final_text == "正式梗"


def test_complete_original_contract_from_supervisor_is_supported(tmp_path):
    payload = {
        "status": "WAITING_HUMAN_EVALUATION",
        "stop_node": "H02",
        "complete_original": {
            "hook_text": "原梗标题",
            "complete_reference_text": "完整原梗",
        },
        "final_draft": {"title": "正式标题", "text": "正式梗"},
    }
    write_result(tmp_path, payload)

    parsed = parse_run_result(tmp_path)

    assert parsed.original_title == "原梗标题"
    assert parsed.original_text == "完整原梗"


def test_stop_status_contract_from_supervisor_is_supported(tmp_path):
    payload = {
        "stop_status": "WAITING_HUMAN_EVALUATION",
        "stop_node": "H02",
        "complete_reference": {"complete_reference_text": "完整原梗"},
        "final_draft": {"text": "正式梗"},
    }
    write_result(tmp_path, payload)

    parsed = parse_run_result(tmp_path)

    assert parsed.original_text == "完整原梗"
    assert parsed.final_text == "正式梗"


def test_nested_execution_and_ledger_contract_is_supported(tmp_path):
    payload = {
        "execution": {
            "status": "WAITING_HUMAN_EVALUATION",
            "stop_node": "H02",
        },
        "stop": {"node": "H02", "status": "WAITING_HUMAN_EVALUATION"},
        "ledger": {
            "complete_reference": {
                "hook_text": "原梗标题",
                "complete_reference_text": "完整原梗",
            },
            "final_draft": {
                "final_title": "正式标题",
                "final_text": "正式梗",
            },
        },
    }
    write_result(tmp_path, payload)

    parsed = parse_run_result(tmp_path)

    assert parsed.original_title == "原梗标题"
    assert parsed.original_text == "完整原梗"
    assert parsed.final_title == "正式标题"
    assert parsed.final_text == "正式梗"


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


def test_extract_compact_metrics_maps_aggregate_multi_session_usage(tmp_path):
    (tmp_path / "metrics.json").write_text(
        json.dumps(
            {
                "schema_version": "compact-round-metrics-v1",
                "orchestrator_kind": "PROGRAMMATIC_NO_LLM_PARENT",
                "token_usage": {
                    "session_count": 5,
                    "raw_input_tokens": 484842,
                    "cached_input_tokens": 390272,
                    "non_cached_input_tokens": 94570,
                    "output_tokens": 8412,
                    "reasoning_output_tokens": 2103,
                },
            }
        ),
        encoding="utf-8",
    )

    assert extract_compact_metrics(tmp_path) == {
        "input_tokens": 484842,
        "cached_input_tokens": 390272,
        "output_tokens": 8412,
        "reasoning_tokens": 2103,
    }


def test_extract_usage_preserves_last_compact_stage_when_metrics_file_is_missing():
    events = [
        {
            "type": "compact.stage.completed",
            "stage": "BOUNDARY_01",
            "cumulative_usage": {
                "input_tokens": 120,
                "cached_input_tokens": 90,
                "output_tokens": 12,
                "reasoning_tokens": 4,
            },
        },
        {
            "type": "compact.stage.completed",
            "stage": "VARIANTS_01",
            "cumulative_usage": {
                "input_tokens": 310,
                "cached_input_tokens": 240,
                "output_tokens": 31,
                "reasoning_tokens": 9,
            },
        },
    ]

    assert extract_usage(events) == {
        "input_tokens": 310,
        "cached_input_tokens": 240,
        "output_tokens": 31,
        "reasoning_tokens": 9,
    }
