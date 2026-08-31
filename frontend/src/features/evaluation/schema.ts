export const processingFields = [
  ['original_meme_popularity', '原始梗传播度'], ['original_meme_applicability', '原始梗适用性'],
  ['search_result_relevance', '搜索结果相关性'], ['variant_evidence_quality', '变式证据质量'],
  ['template_extraction_accuracy', '模板提取准确度'], ['overall_chain_reasonableness', '处理链整体合理性'],
] as const

export const candidateSetFields = [
  ['effective_difference', '候选有效差异'], ['natural_rewrite_coverage', '自然改写思路覆盖'],
  ['overall_selectable_quality', '整体达到可选择水平'],
] as const

export const candidateFields = [
  ['fluency', '通顺度'], ['original_meme_recognition', '原梗辨识度'],
  ['agu_zao_naturalness', 'agu 凿融合自然度'], ['humor', '好笑程度'], ['template_logic', '模板逻辑'],
] as const

export const finalFields = [
  ['fluency', '通顺度'], ['original_meme_recognition', '原梗辨识度'], ['agu_zao_fit', '凿 agu 契合度'],
  ['humor', '好笑程度'], ['overall_satisfaction', '整体满意度'],
] as const

export const candidateIds = ['C1', 'C2', 'C3', 'C4', 'C5'] as const

type CandidateId = typeof candidateIds[number]
export interface EvaluationFormValues {
  processing_chain: { original_meme_popularity:number; original_meme_applicability:number; search_result_relevance:number; variant_evidence_quality:number; template_extraction_accuracy:number; overall_chain_reasonableness:number; comment:string }
  candidate_set: { effective_difference:number; natural_rewrite_coverage:number; overall_selectable_quality:number; comment:string }
  candidates: Record<CandidateId, { fluency:number; original_meme_recognition:number; agu_zao_naturalness:number; humor:number; template_logic:number; usability:'USABLE'|'USABLE_AFTER_EDIT'|'UNUSABLE'; modification_advice:string }>
  final_result: { is_best_candidate:boolean; better_candidate_id?:CandidateId; fluency:number; original_meme_recognition:number; agu_zao_fit:number; humor:number; overall_satisfaction:number; comment:string }
  main_problem_nodes: string[]
  admission: { decision?: 'ADMIT'|'NOT_ADMIT'; override?: 'KEEP'|'OVERRIDE_TO_ADMIT'|'OVERRIDE_TO_NOT_ADMIT'; reason: string }
  overall_comment: string
}

export interface HumanEvaluationPayload extends Omit<EvaluationFormValues, 'final_result'|'admission'> {
  expected_run_version: number
  branch_id: string
  final_result: Omit<EvaluationFormValues['final_result'],'better_candidate_id'> & { better_candidate_id: CandidateId|null }
  admission: { decision: 'ADMIT'|'NOT_ADMIT'|null; override: 'KEEP'|'OVERRIDE_TO_ADMIT'|'OVERRIDE_TO_NOT_ADMIT'|null; reason: string }
}

export function buildEvaluationPayload(values:EvaluationFormValues, admissionMode:'HUMAN'|'AUTO', expectedRunVersion:number, branchId:string):HumanEvaluationPayload {
  return {
    ...values,
    expected_run_version: expectedRunVersion,
    branch_id: branchId,
    final_result: { ...values.final_result, better_candidate_id: values.final_result.better_candidate_id ?? null },
    admission: admissionMode === 'HUMAN'
      ? { decision: values.admission.decision ?? null, override: null, reason: values.admission.reason }
      : { decision: null, override: values.admission.override ?? null, reason: values.admission.reason },
  }
}

export function candidateArtifacts(nodes: Array<{ node_key: string; output?: unknown }>) {
  const value = nodes.filter(node => node.node_key === 'N12').at(-1)?.output as Record<string, unknown> | undefined
  const artifact = (value?.artifact ?? value) as Record<string, unknown> | undefined
  const llm = (artifact?.llm ?? artifact) as Record<string, unknown> | undefined
  return Array.isArray(llm?.candidates) ? llm.candidates as Array<Record<string, unknown>> : []
}

export function selectedCandidateId(nodes: Array<{ node_key: string; output?: unknown }>) {
  const value = nodes.filter(node => node.node_key === 'N14').at(-1)?.output as Record<string, unknown> | undefined
  const artifact = (value?.artifact ?? value) as Record<string, unknown> | undefined
  const llm = (artifact?.llm ?? artifact) as Record<string, unknown> | undefined
  return typeof llm?.selected_candidate_id === 'string' ? llm.selected_candidate_id : undefined
}
