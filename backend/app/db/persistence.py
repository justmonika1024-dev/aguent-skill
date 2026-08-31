from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

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
)


def _json(value: Any) -> Any:
    if hasattr(value, "model_dump"): return value.model_dump(mode="json")
    if hasattr(value, "as_dict"): return value.as_dict()
    if isinstance(value, dict): return {str(k): _json(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)): return [_json(v) for v in value]
    if isinstance(value, datetime): return value.isoformat()
    return value


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

    async def create_run(self, context: Any) -> None:
        await self.init()
        async with self.session() as s:
            s.add(RunRecord(id=context.run_id, mode=context.mode.value, status=context.current_state.value,
                            seed_text=context.seed_text, admission_mode=context.admission_mode.value,
                            continuous_enabled=context.continuous_enabled, initial_strategy_version_id=context.strategy_version_id or "",
                            active_branch_id=context.active_branch_id, started_at=context.started_at, created_at=context.started_at))
            s.add(RunBranch(id=context.active_branch_id, run_id=context.run_id, fork_reason="ROOT", is_final_active=True, created_at=context.started_at))
            await s.commit()

    async def persist_event(self, event: Any) -> None:
        async with self.session() as s:
            s.add(RunEvent(id=event.event_id, run_id=event.run_id, sequence=event.sequence, event_type=event.type,
                           run_version=event.run_version, state=event.state, branch_id=event.branch_id,
                           payload_json=_json(event.payload), occurred_at=event.occurred_at))
            await s.commit()

    async def persist_node(self, context: Any, node_key: str, output: Any, outcome: str, status: str = "SUCCEEDED") -> None:
        async with self.session() as s:
            previous = await s.scalar(select(func.max(RunNodeExecution.attempt_no)).where(
                RunNodeExecution.run_id == context.run_id,
                RunNodeExecution.branch_id == context.active_branch_id,
                RunNodeExecution.node_key == node_key))
            execution_id = __import__("uuid").uuid4().hex
            s.add(RunNodeExecution(id=execution_id, run_id=context.run_id, branch_id=context.active_branch_id, node_key=node_key,
                                   attempt_no=(previous or 0) + 1, origin="AGENT", status=status, input_json=_json(context.active_artifacts),
                                   output_json=_json(output), next_state=context.current_node,
                                   strategy_version_id=context.strategy_version_id or "", started_at=context.started_at,
                                   ended_at=context.ended_at))
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

    async def persist_evaluation(self, context: Any, payload: dict[str, Any]) -> None:
        async with self.session() as s:
            decision = payload.get("admission_decision") or payload.get("admission", {}).get("decision")
            s.add(RunHumanEvaluation(id=__import__("uuid").uuid4().hex, run_id=context.run_id,
                                     branch_id=context.active_branch_id, processing_chain_scores_json=_json(payload.get("processing_chain", {})),
                                     candidate_set_scores_json=_json(payload.get("candidate_set", {})), candidate_scores_json=_json(payload.get("candidates", {})), final_result_scores_json=_json(payload.get("final_result", {})),
                                     main_problem_nodes_json=_json(payload.get("main_problem_nodes", [])), admission_decision=decision,
                                     submitted_at=datetime.utcnow()))
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
                row.continuous_enabled = context.continuous_enabled
                n05 = context.node_outputs.get("N05", {})
                n05 = n05.get("llm", n05) if isinstance(n05, dict) else {}
                n14 = context.node_outputs.get("N14", {})
                n14 = n14.get("llm", n14) if isinstance(n14, dict) else {}
                final = context.node_outputs.get("N15", {})
                final_llm = final.get("llm", final) if isinstance(final, dict) else {}
                row.selected_original_title = n05.get("title") if isinstance(n05, dict) else None
                row.selected_original_text = n05.get("original_text") if isinstance(n05, dict) else None
                row.selected_candidate_id = (
                    n14.get("selected_candidate_id") if isinstance(n14, dict) else None
                ) or (final_llm.get("selected_candidate_id") if isinstance(final_llm, dict) else None)
                row.final_agu_text = final_llm.get("final_agu_text") if isinstance(final_llm, dict) else None
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
