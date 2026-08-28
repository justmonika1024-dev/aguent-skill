import uuid
from datetime import datetime

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


def uid() -> str: return str(uuid.uuid4())
def now() -> datetime: return datetime.utcnow()


class RunRecord(Base):
    __tablename__ = "run_records"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    mode: Mapped[str] = mapped_column(String(32)); status: Mapped[str] = mapped_column(String(32))
    seed_text: Mapped[str | None] = mapped_column(Text); admission_mode: Mapped[str] = mapped_column(String(32))
    continuous_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    initial_strategy_version_id: Mapped[str] = mapped_column(String(36)); final_strategy_version_id: Mapped[str | None] = mapped_column(String(36))
    active_branch_id: Mapped[str] = mapped_column(String(36)); selected_original_title: Mapped[str | None] = mapped_column(Text)
    selected_original_text: Mapped[str | None] = mapped_column(Text); selected_candidate_id: Mapped[str | None] = mapped_column(String(32))
    final_agu_text: Mapped[str | None] = mapped_column(Text); admission_decision: Mapped[str | None] = mapped_column(String(32))
    formal_meme_id: Mapped[str | None] = mapped_column(String(36)); total_llm_input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    total_llm_output_tokens: Mapped[int] = mapped_column(Integer, default=0); total_llm_cost_usd: Mapped[float | None] = mapped_column(Numeric(12, 6))
    total_search_cost_usd: Mapped[float] = mapped_column(Numeric(12, 6), default=0); started_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime); termination_reason: Mapped[str | None] = mapped_column(Text); created_at: Mapped[datetime] = mapped_column(DateTime, default=now)


class RunBranch(Base):
    __tablename__ = "run_branches"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid); run_id: Mapped[str] = mapped_column(ForeignKey("run_records.id"), index=True)
    parent_branch_id: Mapped[str | None] = mapped_column(String(36)); forked_from_execution_id: Mapped[str | None] = mapped_column(String(36)); fork_reason: Mapped[str] = mapped_column(Text)
    is_final_active: Mapped[bool] = mapped_column(Boolean, default=True); created_at: Mapped[datetime] = mapped_column(DateTime, default=now)


class RunNodeExecution(Base):
    __tablename__ = "run_node_executions"
    __table_args__ = (UniqueConstraint("run_id", "branch_id", "node_key", "attempt_no"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid); run_id: Mapped[str] = mapped_column(ForeignKey("run_records.id")); branch_id: Mapped[str] = mapped_column(ForeignKey("run_branches.id")); node_key: Mapped[str] = mapped_column(String(64)); attempt_no: Mapped[int] = mapped_column(Integer)
    origin: Mapped[str] = mapped_column(String(32)); status: Mapped[str] = mapped_column(String(32)); input_json: Mapped[dict] = mapped_column(JSON); output_json: Mapped[dict | None] = mapped_column(JSON)
    human_summary: Mapped[str | None] = mapped_column(Text); next_state: Mapped[str | None] = mapped_column(String(64)); prompt_version: Mapped[str | None] = mapped_column(String(64)); strategy_version_id: Mapped[str] = mapped_column(String(36)); provider: Mapped[str | None] = mapped_column(String(32)); model: Mapped[str | None] = mapped_column(String(128)); parameter_snapshot_json: Mapped[dict | None] = mapped_column(JSON); token_usage_json: Mapped[dict | None] = mapped_column(JSON); cost_usd: Mapped[float | None] = mapped_column(Numeric(12, 6)); started_at: Mapped[datetime] = mapped_column(DateTime, default=now); ended_at: Mapped[datetime | None] = mapped_column(DateTime); error_code: Mapped[str | None] = mapped_column(String(64)); error_message: Mapped[str | None] = mapped_column(Text)


def _simple(name, cols):
    table_name = cols.pop("__tablename__", name.lower())
    # Most archive tables use ``id``; the parameter-profile and singleton
    # strategy-state tables intentionally use their named key instead.
    key_name = "id" if "id" in cols else ("profile_name" if "profile_name" in cols else "id")
    return type(name, (Base,), {
        "__tablename__": table_name,
        **{k: mapped_column(v, primary_key=(k == key_name)) for k, v in cols.items()},
    })

# Less frequently accessed archive tables retain the exact database contract while keeping ORM declarations compact.
RunSourceEvidence = _simple("RunSourceEvidence", {"__tablename__":"run_source_evidence", "id":String(36), "run_id":String(36), "branch_id":String(36), "node_execution_id":String(36), "source_id":String(32), "provider":String(32), "title":Text, "url":Text, "canonical_url":Text, "text":Text, "evidence_type":String(32), "content_status":String(32), "retrieved_at":DateTime})
RunSearchBatch = _simple("RunSearchBatch", {"__tablename__":"run_search_batches", "id":String(36), "run_id":String(36), "branch_id":String(36), "node_execution_id":String(36), "query_id":String(32), "query_text":Text, "search_type":String(16), "purpose":Text, "result_limit":Integer, "request_json":JSON, "status":String(32), "created_at":DateTime})
RunEvidenceQueryHit = _simple("RunEvidenceQueryHit", {"__tablename__":"run_evidence_query_hits", "id":String(36), "evidence_id":String(36), "search_batch_id":String(36), "query_id":String(32), "query_text":Text, "search_type":String(16), "purpose":Text})
RunHumanEvaluation = _simple("RunHumanEvaluation", {"__tablename__":"run_human_evaluations", "id":String(36), "run_id":String(36), "branch_id":String(36), "processing_chain_scores_json":JSON, "candidate_set_scores_json":JSON, "candidate_scores_json":JSON, "final_result_scores_json":JSON, "main_problem_nodes_json":JSON, "admission_decision":String(32), "submitted_at":DateTime})
RunStrategyVersion = _simple("RunStrategyVersion", {"__tablename__":"run_strategy_versions", "id":String(36), "version_number":Integer, "parent_version_id":String(36), "strategy_json":JSON, "source_run_id":String(36), "source_evaluation_id":String(36), "change_summary":Text, "created_at":DateTime})
RunStrategyPatch = _simple("RunStrategyPatch", {"__tablename__":"run_strategy_patches", "id":String(36), "source_run_id":String(36), "evaluation_id":String(36), "before_version_id":String(36), "after_version_id":String(36), "feedback_summary":Text, "affected_nodes_json":JSON, "patch_operations_json":JSON, "score_gaps_json":JSON, "next_round_hypotheses_json":JSON, "created_at":DateTime})
RunStrategyState = _simple("RunStrategyState", {"__tablename__":"run_strategy_state", "id":Integer, "active_strategy_version_id":String(36), "updated_at":DateTime})
RunModelParameterProfile = _simple("RunModelParameterProfile", {"__tablename__":"run_model_parameter_profiles", "profile_name":String(32), "parameters_json":JSON, "updated_at":DateTime})
RunAuditAction = _simple("RunAuditAction", {"__tablename__":"run_audit_actions", "id":String(36), "run_id":String(36), "actor":String(32), "action_type":String(64), "target_type":String(64), "target_id":String(36), "detail_json":JSON, "created_at":DateTime})
MemeRecord = _simple("MemeRecord", {"__tablename__":"meme_records", "id":String(36), "title":Text, "normalized_title":String(255), "status":String(32), "original_meme_text":Text, "canonical_template_text":Text, "template_segments_json":JSON, "adaptation_route":String(64), "preserved_features_json":JSON, "rewritten_features_json":JSON, "final_agu_text":Text, "source_run_id":String(36), "source_branch_id":String(36), "initial_admission_mode":String(32), "initial_admission_decision":String(32), "created_at":DateTime, "updated_at":DateTime})
MemeSource = _simple("MemeSource", {"__tablename__":"meme_sources", "id":String(36), "meme_id":String(36), "source_role":String(32), "source_id":String(32), "title":Text, "url":Text, "evidence_quote":Text, "published_date":DateTime, "run_source_evidence_id":String(36), "sort_order":Integer})
MemeAdmissionHistory = _simple("MemeAdmissionHistory", {"__tablename__":"meme_admission_history", "id":String(36), "meme_id":String(36), "decision_source":String(32), "decision":String(32), "reason_json":JSON, "created_at":DateTime})
MemeStatusHistory = _simple("MemeStatusHistory", {"__tablename__":"meme_status_history", "id":String(36), "meme_id":String(36), "from_status":String(32), "to_status":String(32), "reason":Text, "created_at":DateTime})
MemeRevisionHistory = _simple("MemeRevisionHistory", {"__tablename__":"meme_revision_history", "id":String(36), "meme_id":String(36), "source_branch_id":String(36), "revision_reason":String(64), "record_snapshot_json":JSON, "sources_snapshot_json":JSON, "created_at":DateTime})
