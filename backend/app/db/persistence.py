from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.services.strategy import StrategyPatch, StrategyService, default_strategy

from .base import Base
from .models import (
    MemeAdmissionHistory,
    MemeRecord,
    MemeSource,
    RunAPICall,
    RunBranch,
    RunEvent,
    RunHumanEvaluation,
    RunNodeExecution,
    RunRecord,
    RunSearchBatch,
    RunSourceEvidence,
    RunStrategyPatch,
    RunStrategyState,
    RunStrategyVersion,
)

_MODULAR_EVALUATION_KEYS = (
    "original_search_plan",
    "selected_original_meme",
    "variant_search_plan",
    "variant_search_results",
    "template_extraction",
)
_EVALUATION_FEEDBACK_KEY = "_evaluation_feedback"
_EVALUATION_FEEDBACK_SCHEMA_VERSION = 1


def _json(value: Any) -> Any:
    if hasattr(value, "model_dump"): return value.model_dump(mode="json")
    if hasattr(value, "as_dict"): return value.as_dict()
    if isinstance(value, dict): return {str(k): _json(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)): return [_json(v) for v in value]
    if isinstance(value, datetime): return value.isoformat()
    return value


def _run_summary_payloads(context: Any) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    n05 = context.node_outputs.get("N05", {})
    n05 = n05.get("llm", n05) if isinstance(n05, dict) else {}
    n14 = context.node_outputs.get("N14", {})
    n14 = n14.get("llm", n14) if isinstance(n14, dict) else {}
    n15 = context.node_outputs.get("N15", {})
    n15 = n15.get("llm", n15) if isinstance(n15, dict) else {}
    return n05, n14, n15


class SQLiteRepository:
    def __init__(self, database_url: str = "sqlite+aiosqlite:///./data/agugent.db") -> None:
        self.engine = create_async_engine(database_url)
        self._sessions = async_sessionmaker(self.engine, expire_on_commit=False)
        self._initialized = False

    @asynccontextmanager
    async def session(self):
        async with self._sessions() as session:
            yield session

    async def init(self) -> None:
        if self._initialized:
            return
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        self._initialized = True

    async def ensure_active_strategy(self) -> tuple[str, dict[str, Any]]:
        await self.init()
        async with self.session() as s, s.begin():
            state = await s.get(RunStrategyState, 1)
            if state is None:
                version_id = str(uuid4())
                strategy = default_strategy()
                now = datetime.now(UTC)
                s.add(RunStrategyVersion(
                    id=version_id,
                    version_number=1,
                    parent_version_id=None,
                    strategy_json=strategy,
                    source_run_id=None,
                    source_evaluation_id=None,
                    change_summary="Default strategy",
                    created_at=now,
                ))
                s.add(RunStrategyState(
                    id=1,
                    active_strategy_version_id=version_id,
                    updated_at=now,
                ))
                return version_id, strategy
            version = await s.get(RunStrategyVersion, state.active_strategy_version_id)
            if version is None:
                raise RuntimeError("active strategy version does not exist")
            return version.id, _json(version.strategy_json)

    async def apply_strategy_patch(
        self,
        *,
        source_run_id: str,
        evaluation_id: str,
        before_version_id: str,
        patch: StrategyPatch | dict[str, Any],
    ) -> tuple[str, dict[str, Any]]:
        await self.init()
        async with self.session() as s, s.begin():
            state = await s.get(RunStrategyState, 1)
            if state is None or state.active_strategy_version_id != before_version_id:
                raise ValueError("before strategy version is not active")
            before = await s.get(RunStrategyVersion, before_version_id)
            if before is None:
                raise ValueError("before strategy version does not exist")
            after = StrategyService().apply(before.strategy_json, patch)
            next_version = (await s.scalar(select(func.max(RunStrategyVersion.version_number))) or 0) + 1
            after_version_id = str(uuid4())
            patch_id = str(uuid4())
            now = datetime.now(UTC)
            payload = patch if isinstance(patch, dict) else {
                "operations": patch.operations,
                "feedback_summary": patch.feedback_summary,
                "affected_nodes": patch.affected_nodes or [],
            }
            operations = payload.get("patch_operations", payload.get("operations", []))
            s.add(RunStrategyVersion(
                id=after_version_id,
                version_number=next_version,
                parent_version_id=before_version_id,
                strategy_json=after,
                source_run_id=source_run_id,
                source_evaluation_id=evaluation_id,
                change_summary=payload.get("feedback_summary", ""),
                created_at=now,
            ))
            s.add(RunStrategyPatch(
                id=patch_id,
                source_run_id=source_run_id,
                evaluation_id=evaluation_id,
                before_version_id=before_version_id,
                after_version_id=after_version_id,
                feedback_summary=payload.get("feedback_summary", ""),
                affected_nodes_json=_json(payload.get("affected_nodes", [])),
                patch_operations_json=_json(operations),
                score_gaps_json=_json(payload.get("score_gaps", {})),
                next_round_hypotheses_json=_json(payload.get("next_round_hypotheses", [])),
                created_at=now,
            ))
            state.active_strategy_version_id = after_version_id
            state.updated_at = now
            return after_version_id, after

    async def activate_strategy(self, strategy_id: str) -> str:
        await self.init()
        async with self.session() as s, s.begin():
            version = await s.get(RunStrategyVersion, strategy_id)
            if version is None:
                raise KeyError(strategy_id)
            state = await s.get(RunStrategyState, 1)
            now = datetime.now(UTC)
            if state is None:
                s.add(RunStrategyState(
                    id=1,
                    active_strategy_version_id=strategy_id,
                    updated_at=now,
                ))
            else:
                state.active_strategy_version_id = strategy_id
                state.updated_at = now
        return strategy_id

    async def sync_run_snapshot(self, context: Any) -> None:
        await self.init()
        async with self.session() as s:
            row = await s.get(RunRecord, context.run_id)
            if row is not None:
                n05, n14, final = _run_summary_payloads(context)
                row.status = context.current_state.value
                row.continuous_enabled = context.continuous_enabled
                row.active_branch_id = context.active_branch_id
                row.final_strategy_version_id = context.strategy_version_id
                row.ended_at = context.ended_at
                row.selected_original_title = n05.get("title")
                row.selected_original_text = n05.get("original_text")
                row.selected_candidate_id = (
                    n14.get("selected_candidate_id") or final.get("selected_candidate_id")
                )
                row.final_agu_text = final.get("final_agu_text")
            await s.commit()

    async def create_run(self, context: Any) -> None:
        await self.init()
        async with self.session() as s:
            s.add(RunRecord(id=context.run_id, mode=context.mode.value, status=context.current_state.value,
                            seed_text=context.seed_text, admission_mode=context.admission_mode.value,
                            continuous_enabled=context.continuous_enabled, initial_strategy_version_id=context.strategy_version_id or "",
                            active_branch_id=context.active_branch_id, started_at=context.started_at, created_at=context.started_at))
            s.add(RunBranch(id=context.active_branch_id, run_id=context.run_id, fork_reason="ROOT", is_final_active=True, created_at=context.started_at))
            await s.commit()

    async def persist_corrected_branch(
        self,
        *,
        run_id: str,
        branch_id: str,
        parent_branch_id: str,
        forked_from_execution_id: str | None = None,
    ) -> None:
        await self.init()
        async with self.session() as s, s.begin():
            previous = await s.get(RunBranch, parent_branch_id)
            run = await s.get(RunRecord, run_id)
            if previous is None or previous.run_id != run_id or run is None:
                raise ValueError("cannot fork from an unknown run branch")
            if await s.get(RunBranch, branch_id) is not None:
                raise ValueError("branch already exists")
            previous.is_final_active = False
            s.add(RunBranch(
                id=branch_id,
                run_id=run_id,
                parent_branch_id=parent_branch_id,
                forked_from_execution_id=forked_from_execution_id,
                fork_reason="HUMAN_CORRECTION",
                is_final_active=True,
                created_at=datetime.now(UTC),
            ))
            run.active_branch_id = branch_id

    async def persist_event(self, event: Any) -> None:
        async with self.session() as s:
            s.add(RunEvent(id=event.event_id, run_id=event.run_id, sequence=event.sequence, event_type=event.type,
                           run_version=event.run_version, state=event.state, branch_id=event.branch_id,
                           payload_json=_json(event.payload), occurred_at=event.occurred_at))
            await s.commit()

    async def persist_node(
        self,
        context: Any,
        node_key: str,
        output: Any,
        outcome: str,
        status: str = "SUCCEEDED",
        *,
        started_at: datetime | None = None,
        ended_at: datetime | None = None,
    ) -> None:
        async with self.session() as s:
            previous = await s.scalar(select(func.max(RunNodeExecution.attempt_no)).where(
                RunNodeExecution.run_id == context.run_id,
                RunNodeExecution.branch_id == context.active_branch_id,
                RunNodeExecution.node_key == node_key))
            execution_id = __import__("uuid").uuid4().hex
            s.add(RunNodeExecution(id=execution_id, run_id=context.run_id, branch_id=context.active_branch_id, node_key=node_key,
                                   attempt_no=(previous or 0) + 1, origin="AGENT", status=status, input_json=_json(context.active_artifacts),
                                   output_json=_json(output), next_state=context.current_node,
                                   strategy_version_id=context.strategy_version_id or "",
                                   started_at=started_at or datetime.utcnow(),
                                   ended_at=ended_at or datetime.utcnow()))
            if node_key in {"N04", "N08"} and isinstance(output, dict):
                evidence_type = (
                    "ORIGINAL_SEARCH_RESULT" if node_key == "N04" else "VARIANT_SEARCH_RESULT"
                )
                for query in output.get("queries", []):
                    query_id = str(query.get("query_id", "")) if isinstance(query, dict) else ""
                    s.add(RunSearchBatch(id=__import__("uuid").uuid4().hex, run_id=context.run_id,
                                         branch_id=context.active_branch_id, node_execution_id=execution_id,
                                         query_id=query_id, query_text=query.get("query", "") if isinstance(query, dict) else str(query),
                                         search_type=query.get("search_type", "auto") if isinstance(query, dict) else "auto",
                                         purpose=query.get("purpose", "") if isinstance(query, dict) else "",
                                         result_limit=5 if node_key == "N04" else 10, request_json=_json(query),
                                         status="SUCCEEDED", created_at=datetime.utcnow()))
                for source in output.get("sources", []):
                    s.add(RunSourceEvidence(id=__import__("uuid").uuid4().hex, run_id=context.run_id,
                                            branch_id=context.active_branch_id, node_execution_id=execution_id,
                                            source_id=source.get("source_id", ""), provider="exa",
                                            title=source.get("title", ""), url=source.get("url", ""),
                                            canonical_url=source.get("canonical_url", ""), text=source.get("text", ""),
                                            evidence_type=evidence_type,
                                            content_status=source.get("status", "VALID"), retrieved_at=datetime.utcnow()))
            if node_key == "N09" and isinstance(output, dict):
                payload = output.get("llm", output)
                variants = payload.get("variants", []) if isinstance(payload, dict) else []
                for variant in variants:
                    if not isinstance(variant, dict):
                        continue
                    url = variant.get("source_url", "")
                    s.add(RunSourceEvidence(
                        id=__import__("uuid").uuid4().hex,
                        run_id=context.run_id,
                        branch_id=context.active_branch_id,
                        node_execution_id=execution_id,
                        source_id=variant.get("source_id", ""),
                        provider="exa+llm-validation",
                        title=variant.get("variant_text", "")[:200],
                        url=url,
                        canonical_url=url,
                        text=variant.get("evidence_quote") or variant.get("variant_text", ""),
                        evidence_type="VALIDATED_VARIANT",
                        content_status="VALID",
                        retrieved_at=datetime.utcnow(),
                    ))
            await s.commit()

    async def persist_node_failure(
        self,
        context: Any,
        node_key: str,
        *,
        error_code: str,
        error_message: str,
        started_at: datetime | None = None,
        ended_at: datetime | None = None,
    ) -> None:
        """Persist a failed attempt so the audit chain does not stop silently."""
        await self.init()
        async with self.session() as s:
            previous = await s.scalar(select(func.max(RunNodeExecution.attempt_no)).where(
                RunNodeExecution.run_id == context.run_id,
                RunNodeExecution.branch_id == context.active_branch_id,
                RunNodeExecution.node_key == node_key,
            ))
            s.add(RunNodeExecution(
                id=__import__("uuid").uuid4().hex,
                run_id=context.run_id,
                branch_id=context.active_branch_id,
                node_key=node_key,
                attempt_no=(previous or 0) + 1,
                origin="AGENT",
                status="FAILED",
                input_json=_json(context.active_artifacts),
                output_json=None,
                next_state=None,
                strategy_version_id=context.strategy_version_id or "",
                started_at=started_at or datetime.utcnow(),
                ended_at=ended_at or datetime.utcnow(),
                error_code=error_code,
                error_message=error_message,
            ))
            await s.commit()

    async def mark_run_retried(self, context: Any) -> None:
        """Move a failed in-memory run back to an observable running state."""
        async with self.session() as s:
            row = await s.get(RunRecord, context.run_id)
            if row:
                row.status = "RUNNING"
                row.ended_at = None
                row.termination_reason = None
            await s.commit()

    async def persist_evaluation(self, context: Any, payload: dict[str, Any]) -> None:
        async with self.session() as s:
            admission = payload.get("admission", {})
            override_decisions = {
                "OVERRIDE_TO_ADMIT": "ADMIT",
                "OVERRIDE_TO_NOT_ADMIT": "NOT_ADMIT",
            }
            decision = (
                payload.get("admission_decision")
                or admission.get("decision")
                or override_decisions.get(admission.get("override"))
            )
            processing_chain = {
                key: _json(payload[key])
                for key in _MODULAR_EVALUATION_KEYS
                if key in payload
            }
            if all(key in processing_chain for key in _MODULAR_EVALUATION_KEYS):
                if decision is None:
                    raise ValueError("modular evaluation requires a resolved admission decision")
                processing_chain[_EVALUATION_FEEDBACK_KEY] = {
                    "schema_version": _EVALUATION_FEEDBACK_SCHEMA_VERSION,
                    "admission": _json(admission),
                    "overall_comment": str(payload.get("overall_comment", "")),
                }
            candidate_generation = payload.get("candidate_generation", {})
            s.add(RunHumanEvaluation(
                id=str(payload.get("evaluation_id") or uuid4().hex),
                run_id=context.run_id,
                branch_id=context.active_branch_id,
                processing_chain_scores_json=processing_chain,
                candidate_set_scores_json=_json(candidate_generation.get("overall", {})),
                candidate_scores_json=_json(candidate_generation.get("candidates", {})),
                final_result_scores_json=_json(payload.get("final_result", {})),
                main_problem_nodes_json=_json(payload.get("main_problem_nodes", [])),
                admission_decision=decision,
                submitted_at=datetime.now(UTC),
            ))
            row = await s.get(RunRecord, context.run_id)
            if row:
                row.admission_decision = decision
            await s.commit()

    async def record_api_call(self, run_id: str, *, api_type: str, provider: str, model: str | None = None,
                              provider_request_id: str | None = None, input_tokens: int | None = None,
                              output_tokens: int | None = None, total_tokens: int | None = None,
                              cost_usd: float | None = None, latency_ms: int | None = None,
                              node_key: str | None = None, status: str = "SUCCEEDED") -> None:
        await self.init()
        async with self.session() as s:
            s.add(RunAPICall(run_id=run_id, api_type=api_type, provider=provider, model=model,
                             provider_request_id=provider_request_id, input_tokens=input_tokens,
                             output_tokens=output_tokens, total_tokens=total_tokens, cost_usd=cost_usd,
                             latency_ms=latency_ms, node_key=node_key, status=status))
            await s.commit()

    async def list_formal_meme_titles(self) -> list[dict[str, str]]:
        await self.init()
        async with self.session() as s:
            rows = (await s.execute(
                select(MemeRecord.id, MemeRecord.title)
                .where(MemeRecord.status == "PUBLISHED")
                .order_by(MemeRecord.created_at)
            )).all()
        return [{"id": str(row.id), "title": str(row.title or "")} for row in rows]

    async def get_formal_meme_summary(self, meme_id: str) -> dict[str, str] | None:
        await self.init()
        async with self.session() as s:
            row = await s.get(MemeRecord, meme_id)
        if row is None or row.status != "PUBLISHED":
            return None
        return {
            "id": str(row.id),
            "title": str(row.title or ""),
            "original_meme_text": str(row.original_meme_text or ""),
        }

    async def archive_run(self, context: Any) -> None:
        async with self.session() as s:
            row = await s.get(RunRecord, context.run_id)
            if row:
                row.status = context.current_state.value; row.ended_at = context.ended_at
                row.termination_reason = (
                    context.event_buffer[-1].payload.get("error")
                    if context.current_state.value == "FAILED" and context.event_buffer
                    else None
                )
                row.continuous_enabled = context.continuous_enabled
                n05, n14, final_llm = _run_summary_payloads(context)
                row.selected_original_title = n05.get("title")
                row.selected_original_text = n05.get("original_text")
                row.selected_candidate_id = (
                    n14.get("selected_candidate_id") or final_llm.get("selected_candidate_id")
                )
                row.final_agu_text = final_llm.get("final_agu_text")
                row.total_llm_input_tokens = await s.scalar(select(
                    func.coalesce(func.sum(RunAPICall.input_tokens), 0)
                ).where(RunAPICall.run_id == context.run_id, RunAPICall.api_type == "llm")) or 0
                row.total_llm_output_tokens = await s.scalar(select(
                    func.coalesce(func.sum(RunAPICall.output_tokens), 0)
                ).where(RunAPICall.run_id == context.run_id, RunAPICall.api_type == "llm")) or 0
                row.total_llm_cost_usd = await s.scalar(select(
                    func.coalesce(func.sum(RunAPICall.cost_usd), 0)
                ).where(RunAPICall.run_id == context.run_id, RunAPICall.api_type == "llm"))
                row.total_search_cost_usd = await s.scalar(select(
                    func.coalesce(func.sum(RunAPICall.cost_usd), 0)
                ).where(RunAPICall.run_id == context.run_id, RunAPICall.api_type == "search")) or 0
                if row.admission_decision == "ADMIT" and not row.formal_meme_id:
                    meme_id = __import__("uuid").uuid4().hex
                    row.formal_meme_id = meme_id
                    final_text = final_llm.get("final_agu_text") if isinstance(final_llm, dict) else None
                    title = final_llm.get("title", "凿agu 自动生成梗") if isinstance(final_llm, dict) else "凿agu 自动生成梗"
                    original = n05.get("original_text", context.seed_text or "")
                    n10 = context.node_outputs.get("N10", {})
                    template = n10.get("template", "") if isinstance(n10, dict) else ""
                    if isinstance(n10, dict) and isinstance(n10.get("llm"), dict):
                        template = n10["llm"].get("template", n10["llm"].get("canonical_template_text", template))
                    s.add(MemeRecord(id=meme_id, title=title, normalized_title=title,
                                     status="PUBLISHED", original_meme_text=original,
                                     canonical_template_text=template or "{原梗}，凿agu", template_segments_json={}, adaptation_route="STRUCTURE_PRESERVING_REWRITE",
                                     preserved_features_json={}, rewritten_features_json={}, final_agu_text=final_text or "",
                                     source_run_id=context.run_id, source_branch_id=context.active_branch_id,
                                     initial_admission_mode=context.admission_mode.value, initial_admission_decision="ADMIT",
                                     created_at=datetime.utcnow(), updated_at=datetime.utcnow()))
                    s.add(MemeAdmissionHistory(id=__import__("uuid").uuid4().hex, meme_id=meme_id,
                                               decision_source="HUMAN", decision="ADMIT", reason_json={}, created_at=datetime.utcnow()))
                    s.add(MemeSource(id=__import__("uuid").uuid4().hex, meme_id=meme_id,
                                     source_role="ORIGINAL", source_id=n05.get("source_id", ""),
                                     title=n05.get("title", ""), url=n05.get("source_url", ""),
                                     evidence_quote=n05.get("evidence_quote", original), published_date=None,
                                     run_source_evidence_id="", sort_order=0))
                    n09 = context.node_outputs.get("N09", {})
                    n09 = n09.get("llm", n09) if isinstance(n09, dict) else {}
                    for index, variant in enumerate(n09.get("variants", [])[:20], 1):
                        s.add(MemeSource(id=__import__("uuid").uuid4().hex, meme_id=meme_id,
                                         source_role="VARIANT", source_id=variant.get("source_id", ""),
                                         title=variant.get("variant_text", "")[:100], url=variant.get("source_url", ""),
                                         evidence_quote=variant.get("evidence_quote", ""), published_date=None,
                                         run_source_evidence_id="", sort_order=index))
                await s.commit()
