import { useQuery } from '@tanstack/react-query'
import { api } from '../../api/client'
import { queryKeys } from '../../api/queries'
import type { AdmissionMode, CurrentRunResponse, RunMode, RunRecord, RunSnapshot, UsageSummary } from '../../api/types'

export interface CreateRunInput {
  mode: RunMode
  admission_mode: AdmissionMode
  seed_text?: string
  continuous_enabled: boolean
}

export const createRun = (input: CreateRunInput) => api.post<RunSnapshot>('/runs', input)

export const sendRunCommand = (
  runId: string,
  type: string,
  runVersion?: number,
  payload: Record<string, unknown> = {},
) => api.post<{ accepted: boolean; run_version: number }>(`/runs/${runId}/commands`, {
  command_id: crypto.randomUUID(),
  type,
  expected_run_version: runVersion,
  payload,
})

export function useCurrentRun() {
  return useQuery({
    queryKey: queryKeys.currentRun,
    queryFn: () => api.get<CurrentRunResponse>('/runs/current'),
    refetchInterval: 5_000,
  })
}

export function useTotalUsage() {
  return useQuery({ queryKey: queryKeys.usage, queryFn: () => api.get<UsageSummary>('/usage') })
}

export function useRunRecord(runId: string, realtime = false) {
  return useQuery({ queryKey: queryKeys.runRecord(runId), queryFn: () => api.get<RunRecord>(`/runs/${runId}/record`), enabled: Boolean(runId), refetchInterval: realtime ? 3_000 : false })
}

export function useRunSnapshot(runId: string) {
  return useQuery({
    queryKey: queryKeys.run(runId), queryFn: () => api.get<RunSnapshot>(`/runs/${runId}`), enabled: Boolean(runId),
    refetchInterval: query => {
      const run = query.state.data
      if (!run || run.run_version === undefined || ['COMPLETED','FAILED','TERMINATED'].includes(run.state)) return false
      return 3_000
    },
  })
}

export function useRunUsage(runId: string) {
  return useQuery({ queryKey: queryKeys.runUsage(runId), queryFn: () => api.get<UsageSummary>(`/runs/${runId}/usage`), enabled: Boolean(runId) })
}
