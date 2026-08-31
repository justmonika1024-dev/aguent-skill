import { Tag } from 'antd'
import type { RunState } from '../../api/types'

const labels: Record<RunState, string> = {
  WAITING_START: '等待启动', RUNNING: '运行中', PAUSING: '暂停中', PAUSED: '已暂停',
  WAITING_HUMAN_INTERVENTION: '等待人工干预', WAITING_HUMAN_EVALUATION: '等待人工评价',
  ARCHIVING: '归档中', COMPLETED: '已完成', FAILED: '失败', TERMINATED: '已终止',
}

const colors: Partial<Record<RunState, string>> = {
  RUNNING: 'processing', PAUSING: 'warning', PAUSED: 'default', WAITING_HUMAN_EVALUATION: 'gold',
  WAITING_HUMAN_INTERVENTION: 'orange', COMPLETED: 'success', FAILED: 'error', TERMINATED: 'default',
  ARCHIVING: 'processing',
}

export function RunStatus({ state }: { state: RunState }) {
  return <Tag color={colors[state]}>{labels[state] ?? state}</Tag>
}
