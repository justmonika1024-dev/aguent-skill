import { useQueryClient } from '@tanstack/react-query'
import { useEffect } from 'react'
import { queryKeys } from '../../api/queries'

const REFRESH_EVENTS = ['node.completed', 'node.failed', 'state.changed', 'human.required', 'run.completed', 'stream.reset']

export function useRunEvents(runId?: string) {
  const queryClient = useQueryClient()
  useEffect(() => {
    if (!runId || typeof EventSource === 'undefined') return
    const source = new EventSource(`/api/v1/runs/${runId}/events`)
    const refresh = () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.currentRun })
      void queryClient.invalidateQueries({ queryKey: queryKeys.run(runId) })
      void queryClient.invalidateQueries({ queryKey: queryKeys.runRecord(runId) })
      void queryClient.invalidateQueries({ queryKey: queryKeys.runUsage(runId) })
    }
    REFRESH_EVENTS.forEach((name) => source.addEventListener(name, refresh))
    return () => {
      REFRESH_EVENTS.forEach((name) => source.removeEventListener(name, refresh))
      source.close()
    }
  }, [queryClient, runId])
}
