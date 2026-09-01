import { buildEvaluationPayload, type CandidateScores, type EvaluationFormValues } from './schema'

const candidate: CandidateScores = {
  fluency: 4,
  original_meme_recognition: 4,
  agu_zao_naturalness: 4,
  humor: 4,
  template_logic: 4,
  usability: 'USABLE',
  modification_advice: '',
}

const values: EvaluationFormValues = {
  original_search_plan: {
    anchor_accuracy: 4,
    query_coverage: 4,
    plan_targeting: 4,
    comment: '',
  },
  selected_original_meme: {
    popularity: 4,
    applicability: 4,
    adaptability: 4,
    evidence_reliability: 4,
    comment: '',
  },
  variant_search_plan: {
    slot_replacement_targeting: 4,
    query_diversity: 4,
    ugc_orientation: 4,
    noise_avoidance: 4,
    comment: '',
  },
  variant_search_results: {
    relevance: 4,
    real_variant_ratio: 4,
    independent_evidence_quality: 4,
    variant_diversity: 4,
    comment: '',
  },
  template_extraction: {
    accuracy: 4,
    original_reconstruction: 4,
    variant_coverage: 4,
    slot_rationality: 4,
    comment: '',
  },
  candidate_generation: {
    overall: {
      effective_difference: 4,
      natural_rewrite_coverage: 4,
      overall_selectable_quality: 4,
      comment: '',
    },
    candidates: {
      C1: { ...candidate },
      C2: { ...candidate },
      C3: { ...candidate },
      C4: { ...candidate },
      C5: { ...candidate },
    },
  },
  final_result: {
    is_best_candidate: true,
    fluency: 4,
    original_meme_recognition: 4,
    agu_zao_fit: 4,
    humor: 4,
    overall_satisfaction: 4,
    comment: '',
  },
  main_problem_nodes: ['NO_OBVIOUS_PROBLEM'],
  admission: { decision: 'ADMIT', reason: '' },
  overall_comment: '',
}

it('keeps the complete seven-module contract and empty text for human admission', () => {
  const payload = buildEvaluationPayload(values, 'HUMAN', 7, 'b1')

  expect(Object.keys(payload)).toEqual([
    'original_search_plan',
    'selected_original_meme',
    'variant_search_plan',
    'variant_search_results',
    'template_extraction',
    'candidate_generation',
    'final_result',
    'main_problem_nodes',
    'admission',
    'overall_comment',
    'expected_run_version',
    'branch_id',
  ])
  expect(payload.original_search_plan).toEqual(values.original_search_plan)
  expect(payload.selected_original_meme).toEqual(values.selected_original_meme)
  expect(payload.variant_search_plan).toEqual(values.variant_search_plan)
  expect(payload.variant_search_results).toEqual(values.variant_search_results)
  expect(payload.template_extraction).toEqual(values.template_extraction)
  expect(payload.candidate_generation).toEqual(values.candidate_generation)
  expect(payload.final_result).toEqual({
    ...values.final_result,
    better_candidate_id: null,
  })
  expect(payload.admission).toEqual({ decision: 'ADMIT', override: null, reason: '' })
  expect(payload.overall_comment).toBe('')
  expect(payload.expected_run_version).toBe(7)
  expect(payload.branch_id).toBe('b1')
})

it('submits only an automatic override in automatic admission mode', () => {
  const payload = buildEvaluationPayload(
    { ...values, admission: { override: 'KEEP', reason: '' } },
    'AUTO',
    8,
    'b2',
  )

  expect(payload.admission).toEqual({ decision: null, override: 'KEEP', reason: '' })
})

it('defaults optional text omitted by the form to empty strings', () => {
  const payload = buildEvaluationPayload({
    ...values,
    original_search_plan: { ...values.original_search_plan, comment: undefined },
    selected_original_meme: { ...values.selected_original_meme, comment: undefined },
    variant_search_plan: { ...values.variant_search_plan, comment: undefined },
    variant_search_results: { ...values.variant_search_results, comment: undefined },
    template_extraction: { ...values.template_extraction, comment: undefined },
    candidate_generation: {
      overall: { ...values.candidate_generation.overall, comment: undefined },
      candidates: {
        ...values.candidate_generation.candidates,
        C1: { ...values.candidate_generation.candidates.C1, modification_advice: undefined },
      },
    },
    final_result: { ...values.final_result, comment: undefined },
    admission: { decision: 'ADMIT', reason: undefined },
    overall_comment: undefined,
  } as unknown as EvaluationFormValues, 'HUMAN', 9, 'b3')

  expect(payload.original_search_plan.comment).toBe('')
  expect(payload.selected_original_meme.comment).toBe('')
  expect(payload.variant_search_plan.comment).toBe('')
  expect(payload.variant_search_results.comment).toBe('')
  expect(payload.template_extraction.comment).toBe('')
  expect(payload.candidate_generation.overall.comment).toBe('')
  expect(payload.candidate_generation.candidates.C1.modification_advice).toBe('')
  expect(payload.final_result.comment).toBe('')
  expect(payload.admission.reason).toBe('')
  expect(payload.overall_comment).toBe('')
})
