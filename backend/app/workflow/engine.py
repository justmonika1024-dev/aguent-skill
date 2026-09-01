from __future__ import annotations

import asyncio
import inspect
from copy import copy
from typing import Any
from uuid import uuid4

from .context import AdmissionMode, RunContext, RunMode, RunState, utcnow
from .events import Command, Event, EventBus
from .registry import NodeRegistry
from .transitions import TransitionTable
from .validators import NodeResultValidator


class WorkflowConflict(RuntimeError):
    pass


class WorkflowEngine:
    """Single-active-run asyncio workflow orchestrator."""

    def __init__(self, registry: NodeRegistry | None = None, transitions: TransitionTable | None = None,
                 services: Any = None, archive_service: Any = None, node_registry: NodeRegistry | None = None,
                 repository: Any = None) -> None:
        self.registry = registry or node_registry or NodeRegistry()
        self.transitions = transitions or TransitionTable()
        self.services = services
        self.archive_service = archive_service
        self.repository = repository
        self.validator = NodeResultValidator()
        self.contexts: dict[str, RunContext] = {}
        self.buses: dict[str, EventBus] = {}
        self._tasks: dict[str, asyncio.Task[None]] = {}
        self._commands: dict[str, asyncio.Queue[Command]] = {}
        self._command_results: dict[tuple[str, str], Any] = {}
        self._lock = asyncio.Lock()

    @property
    def active(self) -> RunContext | None:
        return next((c for c in self.contexts.values() if c.current_state not in {
            RunState.COMPLETED, RunState.FAILED, RunState.TERMINATED}), None)

    async def start_run(self, *, mode: RunMode | str, admission_mode: AdmissionMode | str,
                        seed_text: str | None = None, continuous_enabled: bool = False,
                        strategy_snapshot: dict[str, Any] | None = None) -> RunContext:
        async with self._lock:
            if self.active is not None:
                raise WorkflowConflict("an active run already exists")
            mode, admission_mode = RunMode(mode), AdmissionMode(admission_mode)
            if continuous_enabled and mode is not RunMode.AUTO_DISCOVERY:
                raise ValueError("continuous execution is only allowed for AUTO_DISCOVERY")
            strategy_version_id = None
            if self.repository:
                strategy_version_id, strategy_snapshot = await self.repository.ensure_active_strategy()
            context = RunContext(mode=mode, admission_mode=admission_mode, seed_text=seed_text,
                                 continuous_enabled=continuous_enabled,
                                 strategy_version_id=strategy_version_id,
                                 strategy_snapshot=strategy_snapshot or {})
            context.branches[context.active_branch_id] = {"parent_branch_id": None, "origin": "ROOT"}
            self.contexts[context.run_id] = context
            self.buses[context.run_id] = EventBus()
            self._commands[context.run_id] = asyncio.Queue()
            if self.repository:
                await self.repository.create_run(context)
            await self._emit(context, "run.started", {"mode": mode.value})
            task = asyncio.create_task(self._run(context))
            self._tasks[context.run_id] = task
            return context

    async def command(self, run_id: str, command: Command) -> Any:
        async with self._lock:
            return await self._command_locked(run_id, command)

    async def _command_locked(self, run_id: str, command: Command) -> Any:
        context = self.contexts.get(run_id)
        if context is None:
            raise KeyError(run_id)
        cached = self._command_results.get((run_id, command.command_id))
        if cached is not None:
            return cached
        if command.expected_run_version is not None and command.expected_run_version != context.run_version:
            raise WorkflowConflict("RUN_VERSION_CONFLICT")
        restart_failed_node = False
        if command.type == "PAUSE":
            context.pause_requested = True
            context.current_state = RunState.PAUSING
        elif command.type == "TERMINATE":
            context.terminate_requested = True
        elif command.type == "RESUME":
            if context.current_state is RunState.PAUSED:
                context.current_state = context.suspended_state or RunState.RUNNING
                context.pause_requested = False
        elif command.type == "SET_CONTINUOUS_EXECUTION":
            context.continuous_enabled = bool(command.payload.get("enabled"))
        elif command.type == "EVALUATION_SUBMITTED":
            if context.current_state is not RunState.WAITING_HUMAN_EVALUATION:
                raise WorkflowConflict("evaluation is not currently awaited")
            context.pending_human_action = command.payload
            context.current_node = "N18"
            context.current_state = RunState.RUNNING
        elif command.type == "SWITCH_ACTIVE_BRANCH":
            branch_id = command.payload.get("branch_id")
            if branch_id not in context.branches:
                raise ValueError("unknown branch")
            context.active_branch_id = branch_id
        elif command.type == "CORRECT_NODE_OUTPUT":
            branch_id = str(__import__('uuid').uuid4())
            parent_branch_id = context.active_branch_id
            if self.repository:
                await self.repository.persist_corrected_branch(
                    run_id=context.run_id,
                    branch_id=branch_id,
                    parent_branch_id=parent_branch_id,
                    forked_from_execution_id=command.payload.get("forked_from_execution_id"),
                )
            context.branches[branch_id] = {"parent_branch_id": parent_branch_id,
                                           "origin": "HUMAN_CORRECTION", "payload": command.payload}
            context.active_branch_id = branch_id
            context.current_node = command.payload.get("node_key", context.current_node)
            context.current_state = RunState.RUNNING
        elif command.type == "RETRY_NODE":
            if context.current_state is not RunState.FAILED or not context.retry_available:
                raise WorkflowConflict("RETRY_NOT_AVAILABLE")
            retry_node = str(command.payload.get("node_key", context.current_node))
            if retry_node != context.current_node:
                raise ValueError("retry node must be the failed current node")
            other_active = next((
                candidate for candidate_id, candidate in self.contexts.items()
                if candidate_id != run_id and candidate.current_state not in {
                    RunState.COMPLETED, RunState.FAILED, RunState.TERMINATED,
                }
            ), None)
            if other_active is not None:
                raise WorkflowConflict("ACTIVE_RUN_EXISTS")
            previous_task = self._tasks.get(run_id)
            if previous_task is not None and not previous_task.done():
                await asyncio.shield(previous_task)
            context.current_state = RunState.RUNNING
            context.ended_at = None
            context.retry_available = False
            restart_failed_node = True
            if self.repository:
                await self.repository.mark_run_retried(context)
        else:
            raise ValueError(f"unsupported command: {command.type}")
        context.run_version += 1
        result = {"command_id": command.command_id, "accepted": True, "run_version": context.run_version}
        self._command_results[(run_id, command.command_id)] = result
        await self._emit(context, "command.accepted", {"command_type": command.type})
        await self._sync_context(context)
        if restart_failed_node:
            task = asyncio.create_task(self._run(context))
            self._tasks[context.run_id] = task
        return result

    async def submit_evaluation(self, run_id: str, evaluation: dict[str, Any], *,
                                expected_run_version: int, branch_id: str | None = None) -> Any:
        context = self.contexts.get(run_id)
        if context is None:
            raise KeyError(run_id)
        if branch_id is not None and branch_id != context.active_branch_id:
            raise WorkflowConflict("RUN_VERSION_CONFLICT")
        return await self.command(run_id, Command(type="EVALUATION_SUBMITTED",
                                                   expected_run_version=expected_run_version,
                                                   payload=evaluation))

    async def _run(self, context: RunContext) -> None:
        try:
            while context.current_state not in {RunState.COMPLETED, RunState.FAILED, RunState.TERMINATED}:
                if context.terminate_requested:
                    context.current_state, context.ended_at = RunState.TERMINATED, utcnow()
                    await self._emit(context, "run.completed", {"status": "TERMINATED"})
                    await self._sync_context(context)
                    if self.repository:
                        await self.repository.archive_run(context)
                    if self.repository:
                        await self.repository.archive_run(context)
                    break
                if context.pause_requested and context.current_state is RunState.PAUSING:
                    context.suspended_state = RunState.RUNNING
                    context.current_state = RunState.PAUSED
                    context.run_version += 1
                    await self._emit(context, "run.paused", {})
                    await self._sync_context(context)
                    await asyncio.sleep(0.05)
                    continue
                if context.current_state in {RunState.PAUSED, RunState.WAITING_HUMAN_INTERVENTION,
                                              RunState.WAITING_HUMAN_EVALUATION}:
                    await asyncio.sleep(0.05)
                    continue
                context.current_state = RunState.RUNNING
                await self._sync_context(context)
                node = context.current_node
                output: Any
                attempt_started_at = utcnow()
                await self._emit(context, "node.started", {"node_key": node})
                if node == "START":
                    outcome, output = context.mode.value, {"mode": context.mode.value, "seed_text": context.seed_text}
                elif node == "N18" and context.pending_human_action is not None:
                    outcome, output = "EVALUATION_SUBMITTED", context.pending_human_action
                    context.pending_human_action = None
                else:
                    try:
                        n = self.registry.get(node)
                        # Existing node implementations may use the compact one-argument
                        # contract; provider-backed nodes accept ``services`` as well.
                        params = inspect.signature(n.execute).parameters
                        services = {
                            "run_id": context.run_id,
                            "repository": self.repository,
                            "services": self.services,
                            "strategy_version_id": context.strategy_version_id,
                            "strategy_snapshot": context.strategy_snapshot,
                        }
                        result = await (n.execute(context.active_artifacts, services)
                                        if len(params) >= 2 else n.execute(context.active_artifacts))  # type: ignore[call-arg]
                        self.validator.validate(result)
                        if isinstance(result, dict):
                            output = result.get("artifact", result.get("output", result))
                        else:
                            output = getattr(result, "artifact", getattr(result, "output", result))
                        outcome = str(getattr(result, "outcome", None) or (result.get("outcome") if isinstance(result, dict) else "DONE"))
                    except KeyError:
                        # Missing production wiring is an explicit intervention, never success.
                        context.current_state = RunState.WAITING_HUMAN_INTERVENTION
                        await self._emit(context, "node.failed", {"node_key": node, "error": "NODE_NOT_REGISTERED"})
                        await self._sync_context(context)
                        continue
                    except Exception as exc:
                        error_code = (
                            "NODE_TIMEOUT" if isinstance(exc, TimeoutError)
                            else "NODE_OUTPUT_VALIDATION_FAILED" if isinstance(exc, ValueError)
                            else "NODE_EXECUTION_FAILED"
                        )
                        if self.repository:
                            await self.repository.persist_node_failure(
                                context,
                                node,
                                error_code=error_code,
                                error_message=str(exc),
                                started_at=attempt_started_at,
                                ended_at=utcnow(),
                            )
                        context.retry_available = True
                        context.current_state = RunState.FAILED
                        context.ended_at = utcnow()
                        await self._emit(context, "node.failed", {
                            "node_key": node,
                            "error_code": error_code,
                            "error": str(exc),
                            "retry_from_node": node,
                        })
                        await self._sync_context(context)
                        if self.repository:
                            await self.repository.archive_run(context)
                        break
                if node == "N18" and isinstance(output, dict):
                    output = dict(output)
                    output.setdefault("evaluation_id", uuid4().hex)
                if node == "N19" and outcome == "PATCH_VALID" and isinstance(output, dict):
                    output = dict(output)
                    before_version_id = context.strategy_version_id
                    output["before_strategy_version_id"] = before_version_id
                    output["after_strategy_version_id"] = before_version_id
                    if self.repository and before_version_id:
                        evaluation = context.active_artifacts.get("N18", {})
                        evaluation_id = (
                            evaluation.get("evaluation_id")
                            if isinstance(evaluation, dict) else None
                        ) or uuid4().hex
                        try:
                            after_version_id, strategy_snapshot = (
                                await self.repository.apply_strategy_patch(
                                    source_run_id=context.run_id,
                                    evaluation_id=evaluation_id,
                                    before_version_id=before_version_id,
                                    patch=output,
                                )
                            )
                        except Exception as exc:
                            outcome = "PATCH_INVALID"
                            output["patch_error"] = str(exc)
                        else:
                            context.strategy_version_id = after_version_id
                            context.strategy_snapshot = strategy_snapshot
                            output["after_strategy_version_id"] = after_version_id
                context.node_outputs[node] = output
                context.active_artifacts[node] = output
                if self.repository and node != "START":
                    persistence_context = context
                    if node == "N19" and isinstance(output, dict):
                        before_version_id = output.get("before_strategy_version_id")
                        if isinstance(before_version_id, str):
                            persistence_context = copy(context)
                            persistence_context.strategy_version_id = before_version_id
                    await self.repository.persist_node(
                        persistence_context,
                        node,
                        output,
                        outcome,
                        started_at=attempt_started_at,
                        ended_at=utcnow(),
                    )
                if self.repository and node == "N18" and isinstance(output, dict):
                    await self.repository.persist_evaluation(context, output)
                await self._emit(context, "node.completed", {"node_key": node, "outcome": outcome})
                await self._sync_context(context)
                if node == "N18" and outcome == "EVALUATION_SUBMITTED":
                    context.current_node = "N19"
                elif node == "N17" and outcome in {"AUTO_DECIDED", "WAIT_HUMAN_DECISION"}:
                    context.current_node = "N18"
                    context.current_state = RunState.WAITING_HUMAN_EVALUATION
                    context.run_version += 1
                    await self._emit(context, "human.required", {"node_key": "N18"})
                    await self._sync_context(context)
                    continue
                else:
                    nxt = self.transitions.next(node, str(outcome), mode=context.mode.value,
                                                continuous=context.continuous_enabled)
                    if nxt is None:
                        context.current_state, context.ended_at = RunState.COMPLETED, utcnow()
                        await self._emit(context, "run.completed", {"status": "COMPLETED"})
                        await self._sync_context(context)
                        if self.repository:
                            await self.repository.archive_run(context)
                        if self.archive_service:
                            await self.archive_service.archive(context)
                        elif self.repository:
                            await self.repository.archive_run(context)
                        break
                    context.current_node = nxt
                context.run_version += 1
                await self._emit(context, "state.changed", {"current_node": context.current_node})
                await self._sync_context(context)
        finally:
            self._tasks.pop(context.run_id, None)

    async def _emit(self, context: RunContext, event_type: str, payload: dict[str, Any]) -> None:
        event = Event(event_type, context.run_id, context.run_version, context.current_state.value,
                      payload, context.active_branch_id)
        await self.buses[context.run_id].publish(event)
        if self.repository:
            await self.repository.persist_event(event)
        context.event_buffer.append(event)
        if len(context.event_buffer) > 1000:
            del context.event_buffer[:-1000]

    async def _sync_context(self, context: RunContext) -> None:
        if self.repository:
            await self.repository.sync_run_snapshot(context)

    def snapshot(self, run_id: str) -> dict[str, Any]:
        return self.contexts[run_id].snapshot()

    def events(self, run_id: str, since: int = 0) -> tuple[list[Event], bool]:
        return self.buses[run_id].since(since)
