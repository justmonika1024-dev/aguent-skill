import { expect, expectTypeOf, it } from 'vitest'
import type { JsonValue, RunBranch, RunNode, RunRecord } from './types'

type PersistedRunNode = {
  execution_id: string
  execution_order: number
  branch_id: string
  node_key: string
  attempt_no: number
  status: string
  input: JsonValue
  output: JsonValue | null
  error_code: string | null
  error_message: string | null
  started_at: string
  ended_at: string | null
}

type PersistedRunBranch = {
  branch_id: string
  parent_branch_id: string | null
  forked_from_execution_id: string | null
  fork_reason: string
  is_final_active: boolean
}

it('requires the complete persisted node and branch shape in run-record mocks', () => {
  expectTypeOf<RunNode>().toMatchTypeOf<PersistedRunNode>()
  expectTypeOf<RunBranch>().toMatchTypeOf<PersistedRunBranch>()

  const record: RunRecord = {
    run: {
      run_id: 'run-1',
      mode: 'AUTO_DISCOVERY',
      state: 'WAITING_HUMAN_EVALUATION',
    },
    branches: [{
      branch_id: 'branch-1',
      parent_branch_id: null,
      forked_from_execution_id: null,
      fork_reason: 'ROOT',
      is_final_active: true,
    }],
    nodes: [{
      execution_id: 'execution-1',
      execution_order: 0,
      branch_id: 'branch-1',
      node_key: 'N17',
      attempt_no: 1,
      status: 'SUCCEEDED',
      input: {},
      output: null,
      error_code: null,
      error_message: null,
      started_at: '2026-09-02T00:00:00',
      ended_at: '2026-09-02T00:00:01',
    }],
    sources: [],
    evaluations: [],
    events: [],
    api_calls: [],
  }

  expect(record.nodes[0].execution_order).toBe(0)
  expect(record.branches[0].forked_from_execution_id).toBeNull()
})
