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

为了让调用方查看实时进度，请在仓库根目录持续维护合法的 `progress.json`。开始时写入全部字段；每次最新动态变化时更新 `latest_activity`，在 O05 确认完整原梗、模板或长梗骨架确认、G06 形成最终草稿后分别填入对应字段。尚未产生的内容必须为 `null`：

```json
{{
  "latest_activity": "当前正在做什么，以及刚刚确认了什么",
  "original_meme": null,
  "template": null,
  "formal_meme": null
}}
```

`original_meme` 和 `formal_meme` 一旦形成，均使用 `{{"title":"...","text":"..."}}`。`template` 使用字符串；严格槽位分支写入已确认模板，长梗分支写入已确认的宏观骨架。每次覆盖都必须保证文件是完整合法 JSON，不能把搜索摘要或未确认假设写成已确认产物。该文件只是进度快照，不代替 `run-result.json`。

如果形成最终草稿，必须停在 `H02 / WAITING_HUMAN_EVALUATION`，不得代填人工评价。

成功到达 H02 时，`run-result.json` 必须在顶层严格包含以下四个规范字段；可以添加其他字段，但不得改名、嵌套或仅用别名替代：

```json
{{
  "final_state": "WAITING_HUMAN_EVALUATION",
  "stop_node": "H02",
  "complete_reference": {{
    "title": "原梗标题",
    "complete_reference_text": "完整原梗正文"
  }},
  "final_draft": {{
    "title": "正式梗标题",
    "text": "正式梗正文"
  }}
}}
```

在仓库根目录写出：

- `run-result.json`：完整机器记录；
- `search-records.json`：SEARCH_INDEX 和 SOURCE_FETCH 记录；
- `final.md`：人可读摘要；
- `metrics.json`：开始结束时间、耗时、状态、搜索次数、来源抓取数和节点数。

机器记录必须保留完整原梗对象、最终草稿、停止节点、停止状态、节点轨迹、查询、正文证据、模板或长梗骨架、候选和待人工评价数据。最后回复只概括状态和产物路径。
"""
