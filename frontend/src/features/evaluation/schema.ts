export const originalSearchPlanFields = [
  ['anchor_accuracy', '锚点准确度'],
  ['query_coverage', '查询组合覆盖度'],
  ['plan_targeting', '计划针对性'],
] as const

export const selectedOriginalMemeFields = [
  ['popularity', '传播度'],
  ['applicability', '文案梗适用性'],
  ['adaptability', '可反复改编性'],
  ['evidence_reliability', '原始证据可靠性'],
] as const

export const variantSearchPlanFields = [
  ['slot_replacement_targeting', '槽位替换导向'],
  ['query_diversity', '查询多样性'],
  ['ugc_orientation', '真实网友改编来源导向'],
  ['noise_avoidance', '噪声规避能力'],
] as const

export const variantSearchResultsFields = [
  ['relevance', '结果相关性'],
  ['real_variant_ratio', '真实变式比例'],
  ['independent_evidence_quality', '独立证据质量'],
  ['variant_diversity', '变式多样性'],
] as const

export const templateExtractionFields = [
  ['accuracy', '模板准确度'],
  ['original_reconstruction', '原句重建能力'],
  ['variant_coverage', '变式覆盖度'],
  ['slot_rationality', '槽位合理性'],
] as const

export const candidateSetFields = [
  ['effective_difference', '候选有效差异'],
  ['natural_rewrite_coverage', '自然改写思路覆盖'],
  ['overall_selectable_quality', '整体达到可选择水平'],
] as const

export const candidateFields = [
  ['fluency', '通顺度'],
  ['original_meme_recognition', '原梗辨识度'],
  ['agu_zao_naturalness', 'agu 凿融合自然度'],
  ['humor', '好笑程度'],
  ['template_logic', '模板逻辑'],
] as const

export const finalFields = [
  ['fluency', '通顺度'],
  ['original_meme_recognition', '原梗辨识度'],
  ['agu_zao_fit', '凿 agu 契合度'],
  ['humor', '好笑程度'],
  ['overall_satisfaction', '整体满意度'],
] as const

/** @deprecated EvaluationPage will stop consuming this when it moves to module cards. */
export const processingFields = [
  ['original_meme_popularity', '原始梗传播度'],
  ['original_meme_applicability', '原始梗适用性'],
  ['search_result_relevance', '搜索结果相关性'],
  ['variant_evidence_quality', '变式证据质量'],
  ['template_extraction_accuracy', '模板提取准确度'],
  ['overall_chain_reasonableness', '处理链整体合理性'],
] as const

export const candidateIds = ['C1', 'C2', 'C3', 'C4', 'C5'] as const

export type Score = 1 | 2 | 3 | 4 | 5
export type CandidateId = typeof candidateIds[number]
export type CandidateUsability = 'USABLE' | 'USABLE_AFTER_EDIT' | 'UNUSABLE'

interface CommentScores {
  comment: string
}

export interface OriginalSearchPlanScores extends CommentScores {
  anchor_accuracy: Score
  query_coverage: Score
  plan_targeting: Score
}

export interface SelectedOriginalMemeScores extends CommentScores {
  popularity: Score
  applicability: Score
  adaptability: Score
  evidence_reliability: Score
}

export interface VariantSearchPlanScores extends CommentScores {
  slot_replacement_targeting: Score
  query_diversity: Score
  ugc_orientation: Score
  noise_avoidance: Score
}

export interface VariantSearchResultsScores extends CommentScores {
  relevance: Score
  real_variant_ratio: Score
  independent_evidence_quality: Score
  variant_diversity: Score
}

export interface TemplateExtractionScores extends CommentScores {
  accuracy: Score
  original_reconstruction: Score
  variant_coverage: Score
  slot_rationality: Score
}

export interface CandidateScores {
  fluency: Score
  original_meme_recognition: Score
  agu_zao_naturalness: Score
  humor: Score
  template_logic: Score
  usability: CandidateUsability
  modification_advice: string
}

export interface CandidateSetScores extends CommentScores {
  effective_difference: Score
  natural_rewrite_coverage: Score
  overall_selectable_quality: Score
}

export interface CandidateGenerationScores {
  overall: CandidateSetScores
  candidates: Record<CandidateId, CandidateScores>
}

export interface FinalResultScores extends CommentScores {
  is_best_candidate: boolean
  better_candidate_id?: CandidateId
  fluency: Score
  original_meme_recognition: Score
  agu_zao_fit: Score
  humor: Score
  overall_satisfaction: Score
}

export interface EvaluationFormValues {
  original_search_plan: OriginalSearchPlanScores
  selected_original_meme: SelectedOriginalMemeScores
  variant_search_plan: VariantSearchPlanScores
  variant_search_results: VariantSearchResultsScores
  template_extraction: TemplateExtractionScores
  candidate_generation: CandidateGenerationScores
  final_result: FinalResultScores
  main_problem_nodes: string[]
  admission: {
    decision?: 'ADMIT' | 'NOT_ADMIT'
    override?: 'KEEP' | 'OVERRIDE_TO_ADMIT' | 'OVERRIDE_TO_NOT_ADMIT'
    reason: string
  }
  overall_comment: string
}

export interface HumanEvaluationPayload extends Omit<EvaluationFormValues, 'final_result' | 'admission'> {
  expected_run_version: number
  branch_id: string
  final_result: Omit<FinalResultScores, 'better_candidate_id'> & {
    better_candidate_id: CandidateId | null
  }
  admission: {
    decision: 'ADMIT' | 'NOT_ADMIT' | null
    override: 'KEEP' | 'OVERRIDE_TO_ADMIT' | 'OVERRIDE_TO_NOT_ADMIT' | null
    reason: string
  }
}

function withComment<T extends CommentScores>(value: T): T {
  return { ...value, comment: value.comment ?? '' }
}

export function buildEvaluationPayload(
  values: EvaluationFormValues,
  admissionMode: 'HUMAN' | 'AUTO',
  expectedRunVersion: number,
  branchId: string,
): HumanEvaluationPayload {
  const candidates = Object.fromEntries(candidateIds.map((id) => [id, {
    ...values.candidate_generation.candidates[id],
    modification_advice: values.candidate_generation.candidates[id].modification_advice ?? '',
  }])) as Record<CandidateId, CandidateScores>

  return {
    original_search_plan: withComment(values.original_search_plan),
    selected_original_meme: withComment(values.selected_original_meme),
    variant_search_plan: withComment(values.variant_search_plan),
    variant_search_results: withComment(values.variant_search_results),
    template_extraction: withComment(values.template_extraction),
    candidate_generation: {
      overall: withComment(values.candidate_generation.overall),
      candidates,
    },
    final_result: {
      ...values.final_result,
      better_candidate_id: values.final_result.better_candidate_id ?? null,
      comment: values.final_result.comment ?? '',
    },
    main_problem_nodes: values.main_problem_nodes,
    admission: admissionMode === 'HUMAN'
      ? { decision: values.admission.decision ?? null, override: null, reason: values.admission.reason ?? '' }
      : { decision: null, override: values.admission.override ?? null, reason: values.admission.reason ?? '' },
    overall_comment: values.overall_comment ?? '',
    expected_run_version: expectedRunVersion,
    branch_id: branchId,
  }
}

export function candidateArtifacts(nodes: Array<{ node_key: string; output?: unknown }>) {
  const value = nodes.filter((node) => node.node_key === 'N12').at(-1)?.output as Record<string, unknown> | undefined
  const artifact = (value?.artifact ?? value) as Record<string, unknown> | undefined
  const llm = (artifact?.llm ?? artifact) as Record<string, unknown> | undefined
  return Array.isArray(llm?.candidates) ? llm.candidates as Array<Record<string, unknown>> : []
}

export function selectedCandidateId(nodes: Array<{ node_key: string; output?: unknown }>) {
  const value = nodes.filter((node) => node.node_key === 'N14').at(-1)?.output as Record<string, unknown> | undefined
  const artifact = (value?.artifact ?? value) as Record<string, unknown> | undefined
  const llm = (artifact?.llm ?? artifact) as Record<string, unknown> | undefined
  return typeof llm?.selected_candidate_id === 'string' ? llm.selected_candidate_id : undefined
}
