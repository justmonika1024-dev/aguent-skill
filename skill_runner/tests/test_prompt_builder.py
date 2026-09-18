import pytest
from pydantic import ValidationError

from app.prompt_builder import build_prompt
from app.schemas import DynamicExample, RunCreate


def test_manual_seed_requires_nonblank_seed():
    with pytest.raises(ValidationError):
        RunCreate(mode="MANUAL_SEED", seed_text="   ")


def test_auto_forbids_seed():
    with pytest.raises(ValidationError):
        RunCreate(mode="AUTO", seed_text="x")


def test_extra_request_field_is_rejected():
    with pytest.raises(ValidationError):
        RunCreate(mode="AUTO", unexpected=True)


def test_manual_seed_prompt_contains_exact_seed_and_h02_contract():
    prompt = build_prompt(
        RunCreate(mode="MANUAL_SEED", seed_text="我怀疑你在开车，但我没有证据"),
        formal_titles=[],
        dynamic_examples=[],
    )

    assert "mode: MANUAL_SEED" in prompt
    assert "我怀疑你在开车，但我没有证据" in prompt
    assert "H02 / WAITING_HUMAN_EVALUATION" in prompt
    assert "run-result.json" in prompt
    assert "search-records.json" in prompt


def test_auto_prompt_marks_dynamic_examples_as_non_evidence():
    prompt = build_prompt(
        RunCreate(mode="AUTO"),
        formal_titles=["已存在"],
        dynamic_examples=[
            DynamicExample(
                original_title="何以解忧",
                original_text="何以解忧？唯有杜康。",
                final_title="何以解忧？唯有凿agu。",
                final_text="何以解忧？唯有凿agu。",
            ),
        ],
    )

    assert "mode: AUTO" in prompt
    assert "已存在" in prompt
    assert "何以解忧？唯有杜康。" in prompt
    assert "何以解忧？唯有凿agu。" in prompt
    assert "只用于理解改编风格" in prompt
    assert "不能作为本轮网络证据" in prompt
    assert "不能直接复用为本轮结果" in prompt
    assert "Playwright MCP" in prompt
    assert "Exa" in prompt
