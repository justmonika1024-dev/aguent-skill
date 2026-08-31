import { buildEvaluationPayload, type EvaluationFormValues } from './schema'

const values = {
  processing_chain:{comment:'无'},candidate_set:{comment:'无'},candidates:{},
  final_result:{is_best_candidate:true,comment:'无'},main_problem_nodes:['NO_OBVIOUS_PROBLEM'],
  admission:{decision:'ADMIT',reason:'可用'},overall_comment:'无',
} as unknown as EvaluationFormValues

it('normalizes nullable contract fields for human admission',()=>{
  const payload=buildEvaluationPayload(values,'HUMAN',7,'b1')
  expect(payload.final_result.better_candidate_id).toBeNull()
  expect(payload.admission).toEqual({decision:'ADMIT',override:null,reason:'可用'})
  expect(payload.expected_run_version).toBe(7);expect(payload.branch_id).toBe('b1')
})

it('normalizes automatic admission without a human decision',()=>{
  const payload=buildEvaluationPayload({...values,admission:{override:'KEEP',reason:'维持'}},'AUTO',8,'b2')
  expect(payload.admission).toEqual({decision:null,override:'KEEP',reason:'维持'})
})
