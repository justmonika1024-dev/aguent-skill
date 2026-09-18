import json
from collections.abc import Sequence

from .schemas import DynamicExample, RunCreate, RunMode


def _json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2)


def build_prompt(
    request: RunCreate,
    formal_titles: Sequence[str],
    dynamic_examples: Sequence[DynamicExample],
) -> str:
    seed_block = "null"
    if request.mode is RunMode.MANUAL_SEED:
        seed_block = _json({"title": None, "text": request.seed_text})

    examples = [example.model_dump() for example in dynamic_examples]
    mode_guidance = (
        "把人工种子当作待核验线索，按 Skill 的 MANUAL_SEED 默认逻辑执行。"
        if request.mode is RunMode.MANUAL_SEED
        else "执行完整 AUTO_ROUTE 自主发现流程。"
    )
    adaptation_mode = (
        "\nadaptation_mode: AUTO_ROUTE" if request.mode is RunMode.AUTO else ""
    )
    return f"""请使用当前仓库中的 `zao-agugent-supervisor` Skill 执行一轮真实任务。

必须完整遵守 Skill 及其按当前分支要求加载的 references。每轮独立执行，不读取原工作区或用户记忆。{mode_guidance}

输入包：

```yaml
mode: {request.mode.value}
source_scope: COMPLETE_MEME_UNIT{adaptation_mode}
seed: {seed_block}
formal_meme_titles: {_json(list(formal_titles))}
limits:
  max_search_calls: 18
  max_template_expansion_rounds: 2
  continuous_execution: false
tools:
  search_available: true
  source_page_fetch_available: true
  preferred_search_provider: OTHER
```

AUTO 动态示例：

```json
{_json(examples)}
```

上述动态示例只用于理解改编风格，不能作为本轮网络证据，不能计入原梗、变式、模板或传播度证明，也不能直接复用为本轮结果。Skill 内固定示例保持不变。

搜索只能使用本次配置的 Playwright MCP 打开普通搜索页和来源页。不要调用 Exa、curl、web_search 或 Codex Desktop Browser。先真实执行 S00；提供方或证据不足时按状态机合法停止，禁止伪造证据。

如果形成最终草稿，必须停在 `H02 / WAITING_HUMAN_EVALUATION`，不得代填人工评价。

在仓库根目录写出：

- `run-result.json`：完整机器记录；
- `search-records.json`：SEARCH_INDEX 和 SOURCE_FETCH 记录；
- `final.md`：人可读摘要；
- `metrics.json`：开始结束时间、耗时、状态、搜索次数、来源抓取数和节点数。

机器记录必须保留完整原梗对象、最终草稿、停止节点、停止状态、节点轨迹、查询、正文证据、模板或长梗骨架、候选和待人工评价数据。最后回复只概括状态和产物路径。
"""
