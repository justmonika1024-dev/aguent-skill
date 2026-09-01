export type RunMode = 'MANUAL_SEED' | 'AUTO_DISCOVERY'
export type AdmissionMode = 'HUMAN' | 'AUTO'
export type RunState =
  | 'WAITING_START'
  | 'RUNNING'
  | 'PAUSING'
  | 'PAUSED'
  | 'WAITING_HUMAN_INTERVENTION'
  | 'WAITING_HUMAN_EVALUATION'
  | 'ARCHIVING'
  | 'COMPLETED'
  | 'FAILED'
  | 'TERMINATED'

export interface RunSnapshot {
  run_id: string
  run_version?: number
  mode: RunMode
  state: RunState
  current_node?: string
  seed_text?: string | null
  admission_mode?: AdmissionMode
  admission_decision?: string | null
  continuous_enabled?: boolean
  active_branch_id?: string
  formal_meme_id?: string | null
  started_at?: string
  ended_at?: string | null
}

export interface CurrentRunResponse {
  run: RunSnapshot | null
  engine_state: RunState
}

export interface RunNode {
  execution_id?: string
  execution_order?: number
  branch_id?: string
  node_key: string
  attempt_no?: number
  status?: string
  input?: JsonValue
  output?: JsonValue
  error_code?: string | null
  error_message?: string | null
  started_at?: string
  ended_at?: string | null
}

export interface RunBranch {
  branch_id: string
  parent_branch_id?: string | null
  forked_from_execution_id?: string | null
  fork_reason?: string
  is_final_active?: boolean
}

export interface SourceEvidence {
  evidence_id?: string
  node_execution_id?: string
  source_id: string
  provider?: string
  title?: string
  url?: string
  canonical_url?: string
  text?: string
  evidence_type: string
  content_status?: string
}

export interface RunEventRecord {
  sequence: number
  event_type: string
  state: string
  branch_id?: string | null
  payload: Record<string, JsonValue>
  occurred_at: string
}

export interface ApiCallRecord {
  call_id: string
  node_key?: string | null
  api_type: string
  provider: string
  model?: string | null
  input_tokens?: number | null
  output_tokens?: number | null
  total_tokens?: number | null
  cost_usd?: number | null
  latency_ms?: number | null
  status: string
}

export interface RunRecord {
  run: RunSnapshot
  branches: RunBranch[]
  nodes: RunNode[]
  sources: SourceEvidence[]
  evaluations: Array<Record<string, JsonValue>>
  events: RunEventRecord[]
  api_calls: ApiCallRecord[]
}

export interface UsageSummary {
  run_id?: string | null
  calls: number
  llm_calls: number
  search_calls: number
  input_tokens: number
  output_tokens: number
  total_tokens: number
  cost_usd: number
  latency_ms: number
}

export interface MemeRecord {
  id: string
  title: string
  original_meme_text: string
  canonical_template_text: string
  final_agu_text: string
  status: string
  source_run_id: string
  sources?: Array<{ role: string; source_id: string; url: string; evidence_quote: string }>
}

export interface SystemConfig {
  llm_provider: string
  llm_model: string
  api_key_configured: boolean
  search_api_key_configured: boolean
}

export type JsonPrimitive = string | number | boolean | null
export type JsonValue = JsonPrimitive | JsonValue[] | { [key: string]: JsonValue }
