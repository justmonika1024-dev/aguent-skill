#!/usr/bin/env python3
"""Programmatic multi-session runner for a token-bounded 凿agu round."""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any


PLAYWRIGHT_CONFIG = {
    "browser": {
        "browserName": "chromium",
        "isolated": True,
        "launchOptions": {
            "headless": False,
            "channel": "chrome",
            "args": [
                "--window-position=-10000,-10000",
                "--window-size=1280,900",
                "--disable-backgrounding-occluded-windows",
            ],
        },
        "contextOptions": {"viewport": {"width": 1280, "height": 800}},
    }
}


class RoundError(RuntimeError):
    pass


def read_object(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RoundError(f"cannot read {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise RoundError(f"expected JSON object in {path}")
    return value


def write_object(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def final_usage(path: Path) -> dict[str, int]:
    usage: dict[str, int] | None = None
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if event.get("type") == "turn.completed" and isinstance(event.get("usage"), dict):
            current = event["usage"]
            usage = {
                "input_tokens": int(current.get("input_tokens") or 0),
                "cached_input_tokens": int(current.get("cached_input_tokens") or 0),
                "output_tokens": int(current.get("output_tokens") or 0),
                "reasoning_output_tokens": int(current.get("reasoning_output_tokens") or 0),
            }
    if usage is None:
        raise RoundError(f"missing turn.completed usage in {path}")
    return usage


class CodexStageRunner:
    def __init__(
        self,
        command: str,
        workdir: Path,
        playwright_config: Path,
        enable_playwright: bool,
    ) -> None:
        self.command = command
        self.workdir = workdir
        self.playwright_config = playwright_config
        self.enable_playwright = enable_playwright
        self.records: list[dict[str, Any]] = []

    def cumulative_usage(self) -> dict[str, int]:
        return {
            "input_tokens": sum(item["input_tokens"] for item in self.records),
            "cached_input_tokens": sum(
                item["cached_input_tokens"] for item in self.records
            ),
            "output_tokens": sum(item["output_tokens"] for item in self.records),
            "reasoning_tokens": sum(
                item["reasoning_output_tokens"] for item in self.records
            ),
        }

    @staticmethod
    def emit(event: dict[str, Any]) -> None:
        print(json.dumps(event, ensure_ascii=False), flush=True)

    def run(
        self,
        stage: str,
        prompt: str,
        needs_browser: bool,
        load_project_skill: bool = False,
    ) -> None:
        events_path = self.workdir / "search-handoff" / f"{stage.lower()}-events.jsonl"
        stderr_path = self.workdir / "search-handoff" / f"{stage.lower()}-stderr.log"
        command = [
            self.command,
            "exec",
            "--ephemeral",
            "--disable",
            "memories",
        ]
        disabled_features = [
            "plugins",
            "apps",
            "multi_agent_v2",
            "goals",
            "image_generation",
            "in_app_browser",
            "computer_use",
            "hooks",
        ]
        if not load_project_skill:
            disabled_features.append("skill_search")
        for feature in disabled_features:
            command.extend(["--disable", feature])
        if not load_project_skill:
            command.extend(["--enable", "skip_host_skill_discovery"])
        command.extend(
            [
                "--approve-for-me",
                "--json",
                "-c",
                "mcp_servers.node_repl.enabled=false",
                "-C",
                str(self.workdir),
            ]
        )
        if needs_browser and self.enable_playwright:
            playwright_args = json.dumps(
                ["-y", "@playwright/mcp@latest", "--config", str(self.playwright_config)],
                ensure_ascii=False,
            )
            command.extend(
                [
                    "-c",
                    'mcp_servers.playwright.command="npx"',
                    "-c",
                    f"mcp_servers.playwright.args={playwright_args}",
                    "-c",
                    'mcp_servers.playwright.default_tools_approval_mode="approve"',
                ]
            )
        else:
            command.extend(["-c", "mcp_servers.playwright.enabled=false"])
        command.append("-")
        self.emit(
            {
                "type": "compact.stage.started",
                "stage": stage,
                "message": f"正在执行精简阶段 {stage}",
            }
        )
        started = time.monotonic()
        completed = subprocess.run(
            command,
            cwd=self.workdir,
            input=prompt,
            text=True,
            capture_output=True,
            check=False,
        )
        duration = time.monotonic() - started
        events_path.write_text(completed.stdout, encoding="utf-8")
        stderr_path.write_text(completed.stderr, encoding="utf-8")
        try:
            usage = final_usage(events_path)
        except RoundError:
            if completed.returncode != 0:
                self.emit(
                    {
                        "type": "compact.stage.failed",
                        "stage": stage,
                        "exit_code": completed.returncode,
                        "cumulative_usage": self.cumulative_usage(),
                        "message": f"精简阶段 {stage} 执行失败且未上报最终用量",
                    }
                )
                raise RoundError(
                    f"{stage} exited {completed.returncode}; see {stderr_path}"
                )
            raise
        self.records.append(
            {
                "stage": stage,
                "events_path": str(events_path.relative_to(self.workdir)),
                "duration_seconds": round(duration, 3),
                **usage,
            }
        )
        if completed.returncode != 0:
            self.emit(
                {
                    "type": "compact.stage.failed",
                    "stage": stage,
                    "exit_code": completed.returncode,
                    "cumulative_usage": self.cumulative_usage(),
                    "message": f"精简阶段 {stage} 执行失败",
                }
            )
            raise RoundError(f"{stage} exited {completed.returncode}; see {stderr_path}")
        self.emit(
            {
                "type": "compact.stage.completed",
                "stage": stage,
                "duration_seconds": round(duration, 3),
                "usage": {
                    "input_tokens": usage["input_tokens"],
                    "cached_input_tokens": usage["cached_input_tokens"],
                    "output_tokens": usage["output_tokens"],
                    "reasoning_tokens": usage["reasoning_output_tokens"],
                },
                "cumulative_usage": self.cumulative_usage(),
                "message": f"精简阶段 {stage} 已完成",
            }
        )


def discovery_prompt(excluded: list[str]) -> str:
    return f"""STAGE: DISCOVERY
你是一次性 AUTO 候选规划器，不联网、不加载任何 Skill、不生成凿agu正式梗。

提出 3～5 个具体中文纯文本既有梗，排除：{json.dumps(excluded, ensure_ascii=False)}。
每个候选必须尽量是完整闭合原句，并给出两条具体、可被网页核验的疑似槽位替换变式原句；仅“感觉很流行”不够。严格区分“确实记得在网页、评论、聚合回答或梗盘点中见过的具体文本”和“顺手按语法编出的可能句子”：后者即使通顺也不是可靠变式记忆，删除该候选。每项还要给出 1～3 个 `source_hints`（记忆中的平台、聚合页特征、标题片段或可精确搜索的独特短语）以及 `memory_confidence=HIGH|MEDIUM`；这仍是检索假设，不是证据。第一候选必须是 `HIGH`，并且至少一条疑似变式真实改变动作、事件、角色或关键判断等高价值位置。优先：已有明显套改家族，且该位置可自然承载“某人凿agu”。降低只有转载、释义、回应、歌词引用或仅凭高生产力句法就能现场造句的候选排序。
候选排序前做一次最小回填检验：两条疑似变式必须共同证明同一个连续位置真实变化。对每项写出一条完整回填草稿，并按槽位词性、固定搭配和整句语法重新朗读；不能只说“可以承载”。
- `DIRECT_STRICT_FILL`：能把凿agu、agu被凿或agu的被凿直接放入同一个已变化位置，且完整回填草稿自然通顺；
- `CONTROLLED_REWRITE`：直接回填不通顺，但存在一个实体槽和与其共指的一个局部谓词，只需这两处联动即可，例如“你→agu”并把同一共指判断改为“得凿他”；必须明确两处，不能伪称直接回填；
- 其他情况降序或删除。若必须改动另一个无关固定片段才能通顺，不能排在前面；若两条疑似变式只是你临场仿写而非记得见过的具体文本，删除该候选。优先级为自然的 `DIRECT_STRICT_FILL`，其次是改动预算明确的 `CONTROLLED_REWRITE`；不要把名词性评价词槽机械填成“凿agu”。

只把模型记忆标为 `HYPOTHESIS_NOT_EVIDENCE`。按上述可靠性排序。写 `search-handoff/discovery-result.json`：
{{"candidates":[{{"title":"...","hook_text":"...","suspected_variants":["...","..."],"source_hints":["..."],"memory_confidence":"HIGH|MEDIUM","agu_mapping_hypothesis":"...","status":"HYPOTHESIS_NOT_EVIDENCE"}}]}}
最多 5 项。写完校验 JSON。最终只报告文件路径。
"""


def boundary_prompt(hook: str) -> str:
    return f"""STAGE: BOUNDARY
你是一次性网页证据 worker，只核验一个中文梗钩子的 COMPLETE_MEME_UNIT；不加载完整 Skill、不提取模板、不生成凿agu文案。

钩子：{json.dumps(hook, ensure_ascii=False)}

仅使用已配置 Playwright MCP 的百度普通网页搜索与来源正文。不要用 `list_mcp_resources` 或 `list_mcp_resource_templates` 判断工具是否存在；资源列表为空不代表工具不可用，必须先直接调用 `browser_run_code_unsafe`，只有该真实调用返回 unavailable 才可标记 BLOCKED。最多 3 个查询、3 个来源页。浏览器操作必须优先使用 `browser_run_code_unsafe`，最多两次批处理调用：第一次在一段代码内依次执行全部搜索并返回裁剪后的卡片，第二次在一段代码内依次打开选中来源并返回命中附近正文；不要逐页交替调用 browser_navigate 和 browser_evaluate。禁止 web_search、curl、Exa、browser_snapshot 和整页 body；搜索卡片最多 8 条、snippet 最多 160 字，来源只读命中附近最多 1600 字。摘要不是证据。

完整单元是能独立承载铺垫与收束的最小闭合传播单元，不是最长文本。若钩子既作为独立短句传播、又属于带额外呼喊或上下文的长支系，必须同时记录 `SHORT_BRANCH` 与 `LONG_BRANCH`；不要仅因找到更长出处就覆盖可独立成立的短支系。根据后续最可能被同族变式逐字套用的边界选择一个版本，但所有版本都必须有正文来源。

把标准结果写到 `search-handoff/boundary-result.json`，不超过 8KB：
{{"status":"VERIFIED|INCOMPLETE|BLOCKED","hook_text":"...","complete_reference_text":"...","boundary_start":"...","boundary_end":"...","closure_reason":"...","source":{{"title":"...","url":"...","locator":"..."}},"versions":[{{"version_ref":"V1","text":"...","relationship":"SHORT_BRANCH|LONG_BRANCH|WORDING_VARIANT","closure_reason":"...","source":{{"title":"...","url":"...","locator":"..."}}}}],"selected_version_ref":"V1","queries":[{{"query":"...","purpose":"...","outcome":"..."}}],"limits_used":{{}},"integrity":{{"source_body_verified":true}}}}
`VERIFIED` 必须有标题、URL、定位和逐字完整原梗；不得凭记忆补全。complete_reference_text 必须逐字等于 selected_version_ref 指向版本的 text，顶层 source 同步物化该版本来源。写完校验 JSON。最终只报告状态与路径。
"""


def variants_prompt(reference: str, adaptation_mode: str) -> str:
    return f"""STAGE: VARIANTS
你是一次性网页证据 worker，只从来源正文寻找原梗的真实改编；不加载完整 Skill、不提取模板、不生成凿agu文案。

已核验完整原梗：{json.dumps(reference, ensure_ascii=False)}
请求模式：{adaptation_mode}

仅使用已配置 Playwright MCP 的百度普通网页搜索与来源正文。不要用 `list_mcp_resources` 或 `list_mcp_resource_templates` 判断工具是否存在；资源列表为空不代表工具不可用，必须先直接调用 `browser_run_code_unsafe`，只有该真实调用返回 unavailable 才可标记 BLOCKED。最多 4 个查询、4 个来源页。浏览器操作必须优先使用 `browser_run_code_unsafe` 批量完成：一次调用批量跑全部搜索查询，一次调用批量打开选中来源并只返回命中附近正文；不要逐页交替调用 browser_navigate 和 browser_evaluate。禁止 web_search、curl、Exa、browser_snapshot 和整页 body；搜索卡片最多 8 条、snippet 最多 160 字，来源只读命中附近最多 1600 字。摘要不是证据。

先用完整原句、相隔固定锚点、改编/版本/段子及聚合来源特征召回，不预设模板。逐条分类：
- `accepted_variants` 只收所有差异均可由连续槽位替换解释、没有增删分句/前后缀/续写的严格变式；
- `rhythm_variants` 只收保留开场与至少两个相隔辨识锚点、但有结构增删的宏观变式；
- 转载、释义、回应、普通长句偶然匹配和摘要命中写入拒绝计数。

来源页选择的第一优先级是严格变式命中概率：搜索卡片若明确列出多条改编、版本或编号例句，必须先打开该高密度聚合页，不能为了来源多样性跳过它而选择泛化仿写题、释义页或普通讨论。取得至少一条真实严格变式后，再在剩余页面预算中优先让至少 2 条非重复严格变式覆盖至少 2 个独立内容组，并优先覆盖动作、事件、角色或关键判断等高价值位置。同一聚合页已经找到两条也不能因此停止打开其他候选来源；不得为凑内容组降低严格变式标准。

严格变式还必须能由一个最窄的高辨识骨架逐字重建：关系词、分句数量和顺序属于固定锚点，不能把整段尾句或几乎全部文本划成大槽位来吞掉结构变化。开场前缀变化、删除原分句、把“我是说……都是……”改成另一套谓词结构，均不得放入 `accepted_variants`；满足宏观锚点时放入 `rhythm_variants`，否则拒绝。

每条证据必须逐字存在于打开后的正文，含 `verbatim_text/source_url/source_title/locator/content_group/acceptance_reason`。内容组表示独立发布内容，不是语义类别：同一 URL 下的所有条目必须使用同一个 content_group；同一页面中的“冲突行为/职场事件/表演动作”等只能是语义标签，不能冒充独立内容组。写 `search-handoff/variants-initial-result.json`，不超过 12KB：
{{"status":"EVIDENCE_FOUND|INSUFFICIENT|BLOCKED","complete_reference_text":"...","accepted_variants":[],"rhythm_variants":[],"queries":[],"rejected_counts":{{}},"limits_used":{{}},"integrity":{{"source_body_verified":true}}}}
最多各保留 4 条。写完校验 JSON。最终只报告状态与路径。
"""


def coverage_prompt(adaptation_mode: str, allow_micro: bool = True) -> str:
    decision_rule = (
        "证据尚少但已有可信骨架时用 MICRO，最多给 2 条中文精确短句查询。"
        if allow_micro
        else "这是 micro 后的最终复审，只能输出 PASS 或 UNSUITABLE，不得再次输出 MICRO。"
    )
    return f"""STAGE: COVERAGE
你是一次性无网络结构覆盖审查器，不加载完整 Skill、不搜索、不生成凿agu正式梗。

读取 `search-handoff/compact-evidence-package.json`。请求模式：{adaptation_mode}。
先复核严格变式能否由共同高辨识骨架和连续槽位替换逐字重建。程序差异只是观察事实，不是模板。

输出 `search-handoff/coverage-plan.json`：
{{
  "decision":"PASS|MICRO|UNSUITABLE",
  "adaptation_route":"STRICT_SLOT|LONG_FORM|UNSUITABLE",
  "provisional_fixed_anchors":[],
  "generation_value_targets":[{{"target_span":"...","reason":"...","coverage_status":"COVERED|UNCOVERED","evidence_refs":[]}}],
  "micro_queries":[{{"query":"...","purpose":"...","retrieval_hypotheses":[]}}],
  "reason":"..."
}}

STRICT_SLOT 的 PASS 要求原句之外至少 2 条非重复严格变式、至少 2 个内容组，并且至少一个可承载凿agu的动作/事件/角色/判断位置有真实差异覆盖。两条变式已经来自两个内容组且高价值位置已覆盖时直接 PASS，不为凑第三条启动 MICRO；已有两条但内容组不足或高价值位置未覆盖时才可 MICRO；只有一条严格变式时证据不足，输出 UNSUITABLE。数量够但高价值位置未覆盖时不得 PASS。{decision_rule} 假设值必须列入 `retrieval_hypotheses`，检索假设不是证据。没有可信结构用 UNSUITABLE。LONG_FORM 有真实节奏变式即可 PASS，不强制槽位覆盖。写完校验 JSON。最终只报告路径。
"""


def micro_prompt(plan: dict[str, Any], reference: str) -> str:
    return f"""STAGE: MICRO
你是一次性定向网页证据 worker，只验证覆盖计划中的查询；不加载完整 Skill、不提取模板、不生成凿agu文案。

完整原梗：{json.dumps(reference, ensure_ascii=False)}
覆盖计划：{json.dumps(plan, ensure_ascii=False)}

只执行计划内最多 2 条查询，查询 URL 必须显式使用 `https://www.baidu.com/s?wd=...`，不得切换或重定向到 Google、Bing 或其他搜索引擎。不要用 `list_mcp_resources` 或 `list_mcp_resource_templates` 判断工具是否存在；资源列表为空不代表工具不可用，必须先直接调用 Playwright MCP 的 `browser_run_code_unsafe`，只有该真实调用返回 unavailable 才可标记 BLOCKED。用它批量完成：一次调用依次执行全部查询，一次调用批量打开最多 2 个来源并裁剪命中正文；不要逐页交替调用 browser_navigate 和 browser_evaluate。不要寻找 node_repl，也不要因为 node_repl 不存在而跳过已经可用的 Playwright 工具。`retrieval_hypotheses` 只是检索假设不是证据。禁止 web_search、curl、Exa、browser_snapshot 和整页 body。只有来源正文逐字可见、独立成条且属于严格连续槽位替换的文本才能接受。

写 `search-handoff/variants-micro-result.json`：
{{"status":"EVIDENCE_FOUND|INSUFFICIENT|BLOCKED","accepted_variants":[],"queries":[],"rejected_counts":{{}},"integrity":{{"source_body_verified":true,"hypotheses_used_as_evidence":false}}}}
每条接受项字段与首批 worker 相同，最多 3 条。写完校验 JSON。最终只报告路径。
"""


def final_prompt(
    mode: str,
    adaptation_mode: str,
    seed: str | None,
    formal_titles: list[str],
    dynamic_examples: list[dict[str, Any]],
    rejected_candidates: list[dict[str, Any]],
) -> str:
    return f"""STAGE: FINAL
使用当前项目的 `zao-agugent-supervisor` Skill，从程序化外部搜索交接继续并完成一轮；本会话禁止联网、禁止打开浏览器、禁止再启动子会话。
这是 `STAGE: FINAL` 精简交接路径。读取 `SKILL.md` 后只再读取 `references/compact-final-supervisor.md`、下列两份交接 JSON 和必要的失败候选摘要；不得再打开其他 reference、worker JSONL、stderr、DOM 或网页正文。

输入：
- mode: {mode}
- adaptation_mode: {adaptation_mode}
- seed: {json.dumps(seed, ensure_ascii=False)}
- formal_meme_titles: {json.dumps(formal_titles, ensure_ascii=False)}
- dynamic_examples: {json.dumps(dynamic_examples, ensure_ascii=False)}
- rejected_candidates: {json.dumps(rejected_candidates, ensure_ascii=False)}
- 唯一搜索证据：`search-handoff/compact-evidence-package.json`
- 覆盖审查：`search-handoff/coverage-plan.json`

动态示例只用于风格，不是网络证据。先校验精简包来源绑定、证据分类、数量和覆盖审查；不合格则合法停止，不能脑补。合格时按 Skill 完成模板/节奏、契约、适用性、候选、硬审计、评分与选择。搜索事实标 `TOOL_EXECUTED` 并引用交接文件，不能冒称本会话亲自搜索。

必须写：
- `run-result.json`：完整机器记录；若成功，顶层含 `final_state=WAITING_HUMAN_EVALUATION`、`stop_node=H02`、`complete_reference.title/complete_reference_text`、`final_draft.title/text`；
- `search-records.json`：只引用精简查询、来源和 worker 文件，不复制网页正文噪声；
- `final.md`：人可读摘要。

形成正式草稿后必须停在 H02，人工评价字段保持空，不能入库或下一轮。不要创建或估算 `metrics.json`；外层程序会在本会话真正结束后汇总全部会话用量。最终只报告状态和文件路径。
"""


def run_helper(skill_root: Path, workdir: Path, workers: list[Path]) -> None:
    command = [
        sys.executable,
        str(skill_root / "scripts" / "compact_search_handoff.py"),
        "build",
        "--boundary",
        str(workdir / "search-handoff" / "boundary-result.json"),
        "--output",
        str(workdir / "search-handoff" / "compact-evidence-package.json"),
    ]
    for worker in workers:
        command.extend(["--worker", str(worker)])
    completed = subprocess.run(command, text=True, capture_output=True, check=False)
    if completed.returncode != 0:
        raise RoundError(f"compact handoff failed: {completed.stderr.strip()}")


def prepare_skill(skill_root: Path, workdir: Path) -> Path:
    destination = workdir / ".agents" / "skills" / "zao-agugent-supervisor"
    if destination.resolve() == skill_root.resolve():
        return destination
    if not destination.exists():
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(skill_root, destination, ignore=shutil.ignore_patterns(".git", "__pycache__"))
    return destination


def prepare_git(workdir: Path) -> None:
    if (workdir / ".git").exists():
        return
    completed = subprocess.run(
        ["git", "init", "-q"],
        cwd=workdir,
        text=True,
        capture_output=True,
        check=False,
    )
    if completed.returncode != 0:
        raise RoundError(f"cannot initialize run repository: {completed.stderr.strip()}")


def archive_candidate_files(workdir: Path, index: int, names: list[str]) -> None:
    handoff = workdir / "search-handoff"
    for name in names:
        source = handoff / name
        if not source.exists():
            continue
        stem = Path(name).stem
        suffix = Path(name).suffix
        source.replace(handoff / f"rejected-{index:02d}-{stem}{suffix}")


def has_route_evidence(adaptation_mode: str, strict_count: int, rhythm_count: int) -> bool:
    if adaptation_mode == "STRICT_SLOT":
        return strict_count > 0
    if adaptation_mode == "LONG_FORM":
        return rhythm_count > 0
    return strict_count > 0 or rhythm_count > 0


def should_run_micro(coverage: dict[str, Any], strict_count: int) -> bool:
    return coverage.get("decision") == "MICRO" and strict_count >= 2


def validate_final_result(result: dict[str, Any]) -> None:
    if result.get("final_state") != "WAITING_HUMAN_EVALUATION" or result.get("stop_node") != "H02":
        raise RoundError("final supervisor did not reach H02")
    input_record = result.get("input")
    if not isinstance(input_record, dict) or input_record.get("mode") not in {"AUTO", "MANUAL_SEED"}:
        raise RoundError("final result is missing input.mode")
    if result.get("selected_route") not in {"STRICT_SLOT", "LONG_FORM"}:
        raise RoundError("final result is missing selected_route")
    reference = result.get("complete_reference")
    if not isinstance(reference, dict) or not str(reference.get("complete_reference_text") or "").strip():
        raise RoundError("final result is missing complete reference text")
    candidates = result.get("candidates")
    if not isinstance(candidates, list) or not candidates:
        raise RoundError("final result is missing candidates")
    draft = result.get("final_draft")
    if not isinstance(draft, dict) or not str(draft.get("title") or "").strip() or not str(draft.get("text") or "").strip():
        raise RoundError("final result is missing final draft title or text")
    trace = result.get("node_trace")
    if not isinstance(trace, list) or not any(
        isinstance(item, dict) and item.get("node") == "H02" for item in trace
    ):
        raise RoundError("final result node_trace does not include H02")
    evaluation = result.get("human_evaluation")
    modules = evaluation.get("modules") if isinstance(evaluation, dict) else None
    required_modules = {
        "original_search_plan",
        "selected_original",
        "variant_search_plan",
        "variant_search_result",
        "reference_or_template",
        "candidate_set",
        "final_draft",
    }
    if (
        not isinstance(evaluation, dict)
        or evaluation.get("status") != "PENDING"
        or not isinstance(modules, dict)
        or not required_modules.issubset(modules)
    ):
        raise RoundError("final result is missing structured pending human evaluation modules")


def aggregate_metrics(records: list[dict[str, Any]], started: float) -> dict[str, Any]:
    raw = sum(item["input_tokens"] for item in records)
    cached = sum(item["cached_input_tokens"] for item in records)
    return {
        "schema_version": "compact-round-metrics-v1",
        "orchestrator_kind": "PROGRAMMATIC_NO_LLM_PARENT",
        "token_usage": {
            "session_count": len(records),
            "raw_input_tokens": raw,
            "cached_input_tokens": cached,
            "non_cached_input_tokens": raw - cached,
            "output_tokens": sum(item["output_tokens"] for item in records),
            "reasoning_output_tokens": sum(item["reasoning_output_tokens"] for item in records),
        },
        "wall_clock_seconds": round(time.monotonic() - started, 3),
        "session_wall_clock_sum_seconds": round(sum(item["duration_seconds"] for item in records), 3),
        "sessions": records,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=["AUTO", "MANUAL_SEED"], required=True)
    parser.add_argument("--seed")
    parser.add_argument("--adaptation-mode", choices=["AUTO_ROUTE", "STRICT_SLOT", "LONG_FORM"])
    parser.add_argument("--workdir", type=Path, required=True)
    parser.add_argument("--skill-root", type=Path, required=True)
    parser.add_argument("--codex-command", default="codex")
    parser.add_argument("--playwright-config", type=Path)
    parser.add_argument("--formal-title", action="append", default=[])
    parser.add_argument("--dynamic-examples-json", type=Path)
    parser.add_argument("--max-candidates", type=int, default=3)
    parser.add_argument("--no-playwright", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.mode == "MANUAL_SEED" and not args.seed:
        print("ERROR: --seed is required for MANUAL_SEED", file=sys.stderr)
        return 2
    started = time.monotonic()
    workdir = args.workdir.resolve()
    skill_root = args.skill_root.resolve()
    workdir.mkdir(parents=True, exist_ok=True)
    (workdir / "search-handoff").mkdir(exist_ok=True)
    prepare_git(workdir)
    playwright_config = args.playwright_config or (workdir / ".playwright-mcp-config.json")
    if not args.no_playwright and not playwright_config.exists():
        write_object(playwright_config, PLAYWRIGHT_CONFIG)
    adaptation_mode = args.adaptation_mode or ("AUTO_ROUTE" if args.mode == "AUTO" else "STRICT_SLOT")
    dynamic_examples = []
    if args.dynamic_examples_json:
        loaded = json.loads(args.dynamic_examples_json.read_text(encoding="utf-8"))
        if isinstance(loaded, list):
            dynamic_examples = loaded
    runner = CodexStageRunner(
        args.codex_command,
        workdir,
        playwright_config,
        enable_playwright=not args.no_playwright,
    )
    rejected: list[dict[str, Any]] = []
    try:
        if args.mode == "AUTO":
            runner.run("DISCOVERY", discovery_prompt(args.formal_title), needs_browser=False)
            discovery = read_object(workdir / "search-handoff" / "discovery-result.json")
            candidates = discovery.get("candidates") or []
        else:
            candidates = [{"title": "人工种子", "hook_text": args.seed}]
        if not isinstance(candidates, list) or not candidates:
            raise RoundError("no candidates produced")

        selected: dict[str, Any] | None = None
        for index, candidate in enumerate(candidates[: max(1, args.max_candidates)], start=1):
            hook = str(candidate.get("hook_text") or "").strip()
            if not hook:
                continue
            runner.run(f"BOUNDARY_{index:02d}", boundary_prompt(hook), needs_browser=True)
            boundary_path = workdir / "search-handoff" / "boundary-result.json"
            boundary = read_object(boundary_path)
            if boundary.get("status") != "VERIFIED":
                rejected.append({"candidate": candidate, "stage": "BOUNDARY", "reason": boundary.get("status")})
                archive_candidate_files(workdir, index, ["boundary-result.json"])
                continue
            reference = str(boundary.get("complete_reference_text") or "")
            runner.run(f"VARIANTS_{index:02d}", variants_prompt(reference, adaptation_mode), needs_browser=True)
            variants_path = workdir / "search-handoff" / "variants-initial-result.json"
            variants = read_object(variants_path)
            strict_count = len(variants.get("accepted_variants") or [])
            rhythm_count = len(variants.get("rhythm_variants") or [])
            if not has_route_evidence(adaptation_mode, strict_count, rhythm_count):
                rejected.append({"candidate": candidate, "stage": "VARIANTS", "reason": "NO_QUALIFYING_VARIANT"})
                archive_candidate_files(
                    workdir,
                    index,
                    ["boundary-result.json", "variants-initial-result.json"],
                )
                continue
            variant_workers = [variants_path]
            run_helper(skill_root, workdir, variant_workers)
            runner.run(f"COVERAGE_{index:02d}", coverage_prompt(adaptation_mode), needs_browser=False)
            coverage = read_object(workdir / "search-handoff" / "coverage-plan.json")
            if should_run_micro(coverage, strict_count):
                runner.run(
                    f"MICRO_{index:02d}",
                    micro_prompt(coverage, reference),
                    needs_browser=True,
                )
                micro_path = workdir / "search-handoff" / "variants-micro-result.json"
                variant_workers.append(micro_path)
                run_helper(skill_root, workdir, variant_workers)
                runner.run(
                    f"COVERAGE_FINAL_{index:02d}",
                    coverage_prompt(adaptation_mode, allow_micro=False),
                    needs_browser=False,
                )
                coverage = read_object(workdir / "search-handoff" / "coverage-plan.json")
            elif coverage.get("decision") == "MICRO":
                coverage = {
                    **coverage,
                    "decision": "UNSUITABLE",
                    "adaptation_route": "UNSUITABLE",
                    "reason": "MICRO_BASE_TOO_THIN: fewer than two strict variants",
                }
                write_object(workdir / "search-handoff" / "coverage-plan.json", coverage)
            if coverage.get("decision") != "PASS":
                rejected.append(
                    {
                        "candidate": candidate,
                        "stage": "COVERAGE",
                        "reason": coverage.get("reason") or coverage.get("decision"),
                    }
                )
                archive_candidate_files(
                    workdir,
                    index,
                    [
                        "boundary-result.json",
                        "variants-initial-result.json",
                        "variants-micro-result.json",
                        "compact-evidence-package.json",
                        "coverage-plan.json",
                    ],
                )
                if args.mode == "MANUAL_SEED":
                    break
                continue
            selected = candidate
            break
        if selected is None:
            raise RoundError("all candidates exhausted without passing coverage")

        # Search workers receive self-contained stage prompts.  Installing the
        # project Skill earlier makes Codex auto-load the entire workflow and
        # defeats both stage isolation and token compaction.
        prepare_skill(skill_root, workdir)
        runner.run(
            "FINAL",
            final_prompt(
                args.mode,
                adaptation_mode,
                args.seed,
                args.formal_title,
                dynamic_examples,
                rejected,
            ),
            needs_browser=False,
            load_project_skill=True,
        )
        result = read_object(workdir / "run-result.json")
        validate_final_result(result)
        write_object(workdir / "metrics.json", aggregate_metrics(runner.records, started))
    except RoundError as exc:
        result_path = workdir / "run-result.json"
        if not result_path.is_file():
            write_object(
                result_path,
                {
                    "schema_version": "compact-orchestrator-stop-v1",
                    "input": {
                        "mode": args.mode,
                        "adaptation_mode": adaptation_mode,
                        "seed": args.seed,
                    },
                    "final_state": "FAILED",
                    "stop_node": "COMPACT_ORCHESTRATOR",
                    "stop_reason": str(exc),
                    "rejected_candidates": rejected,
                },
            )
        write_object(
            workdir / "metrics.json",
            {**aggregate_metrics(runner.records, started), "status": "FAILED", "error": str(exc)},
        )
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    print(json.dumps({"status": "WAITING_HUMAN_EVALUATION", "workdir": str(workdir)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
