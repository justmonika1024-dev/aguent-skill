import { ArrowRightOutlined, PauseOutlined, PlayCircleOutlined, StopOutlined } from '@ant-design/icons'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { Alert, Button, Card, Col, Form, Input, Radio, Row, Space, Statistic, Switch, Typography } from 'antd'
import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { queryKeys } from '../api/queries'
import type { AdmissionMode, RunMode } from '../api/types'
import { RunStatus } from '../features/runs/RunStatus'
import { createRun, sendRunCommand, useCurrentRun, useTotalUsage } from '../features/runs/runApi'
import { useRunEvents } from '../features/runs/useRunEvents'

const modeOptions = [
  { label: '人工种子', value: 'MANUAL_SEED' },
  { label: '自主发现', value: 'AUTO_DISCOVERY' },
]

export function DashboardPage() {
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const current = useCurrentRun()
  const usage = useTotalUsage()
  const [mode, setMode] = useState<RunMode>('MANUAL_SEED')
  const [admissionMode, setAdmissionMode] = useState<AdmissionMode>('HUMAN')
  const [seed, setSeed] = useState('')
  const [continuous, setContinuous] = useState(false)
  const [error, setError] = useState<string>()
  const run = current.data?.run ?? null
  useRunEvents(run?.run_id)

  const start = useMutation({
    mutationFn: createRun,
    onSuccess: (created) => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.currentRun })
      navigate(`/runs/${created.run_id}`)
    },
    onError: (cause: Error) => setError(cause.message),
  })
  const command = useMutation({
    mutationFn: ({ type, payload }: { type: string; payload?: Record<string, unknown> }) =>
      sendRunCommand(run!.run_id, type, run?.run_version, payload),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: queryKeys.currentRun }),
    onError: (cause: Error) => setError(cause.message),
  })

  const submit = () => {
    setError(undefined)
    if (mode === 'MANUAL_SEED' && !seed.trim()) {
      setError('人工种子不能为空')
      return
    }
    start.mutate({
      mode,
      admission_mode: admissionMode,
      seed_text: mode === 'MANUAL_SEED' ? seed.trim() : undefined,
      continuous_enabled: mode === 'AUTO_DISCOVERY' && continuous,
    })
  }

  return (
    <div className="page-stack">
      <div className="page-heading">
        <div><Typography.Title level={2}>工作台</Typography.Title><Typography.Text className="muted">启动、观察并控制唯一活动任务</Typography.Text></div>
        <Space><RunStatus state={run?.state ?? 'WAITING_START'} /></Space>
      </div>
      {error && <Alert type="error" showIcon message={error} closable onClose={() => setError(undefined)} />}
      <Row gutter={[16, 16]}>
        <Col xs={24} sm={12} xl={6}><Card><Statistic title="LLM 调用" value={usage.data?.llm_calls ?? 0} /></Card></Col>
        <Col xs={24} sm={12} xl={6}><Card><Statistic title="搜索调用" value={usage.data?.search_calls ?? 0} /></Card></Col>
        <Col xs={24} sm={12} xl={6}><Card><Statistic title="累计 Token" value={usage.data?.total_tokens ?? 0} /></Card></Col>
        <Col xs={24} sm={12} xl={6}><Card><Statistic title="搜索成本" prefix="$" precision={3} value={usage.data?.cost_usd ?? 0} /></Card></Col>
      </Row>

      {run ? (
        <Card className="surface" title={<Space><RunStatus state={run.state} /><span>当前任务</span></Space>}>
          <Row gutter={[24, 16]}>
            <Col xs={24} md={16}>
              <Typography.Title level={3}>{run.current_node ?? 'START'}</Typography.Title>
              <Typography.Paragraph className="muted">{run.mode === 'MANUAL_SEED' ? '人工种子' : '自主发现'} · {run.run_id}</Typography.Paragraph>
              {run.seed_text && <Typography.Paragraph ellipsis={{ rows: 2 }}>{run.seed_text}</Typography.Paragraph>}
            </Col>
            <Col xs={24} md={8} className="action-column">
              <Space wrap>
                <Button type="primary" icon={<ArrowRightOutlined />} onClick={() => navigate(`/runs/${run.run_id}`)}>查看任务</Button>
                {run.state === 'WAITING_HUMAN_EVALUATION' && <Button onClick={() => navigate(`/runs/${run.run_id}/evaluation`)}>前往评价</Button>}
                {run.state === 'RUNNING' && <Button icon={<PauseOutlined />} onClick={() => command.mutate({ type: 'PAUSE' })}>暂停</Button>}
                {run.state === 'PAUSED' && <Button icon={<PlayCircleOutlined />} onClick={() => command.mutate({ type: 'RESUME' })}>继续</Button>}
                <Button danger icon={<StopOutlined />} onClick={() => command.mutate({ type: 'TERMINATE' })}>终止</Button>
              </Space>
              {run.mode === 'AUTO_DISCOVERY' && <Space><Switch aria-label="持续执行" checked={Boolean(run.continuous_enabled)} onChange={(enabled)=>command.mutate({type:'SET_CONTINUOUS_EXECUTION',payload:{enabled}})}/><Typography.Text className="muted">持续执行</Typography.Text></Space>}
            </Col>
          </Row>
        </Card>
      ) : (
        <Card className="surface" title="启动一轮任务">
          <Form layout="vertical" onFinish={submit}>
            <Form.Item label="运行模式">
              <Radio.Group value={mode} onChange={(event) => setMode(event.target.value)}>
                {modeOptions.map((option) => <Radio.Button key={option.value} value={option.value}>{option.label}</Radio.Button>)}
              </Radio.Group>
            </Form.Item>
            {mode === 'MANUAL_SEED' && <Form.Item label="人工种子" htmlFor="seed-text" required><Input.TextArea id="seed-text" required rows={4} value={seed} onChange={(event) => setSeed(event.target.value)} placeholder="输入一个能在搜索引擎找到的中文文案梗" /></Form.Item>}
            <Row gutter={24}>
              <Col xs={24} md={12}><Form.Item label="准入模式"><Radio.Group value={admissionMode} onChange={(event) => setAdmissionMode(event.target.value)} options={[{ label: '人工决定', value: 'HUMAN' }, { label: 'Agent 自动准入', value: 'AUTO' }]} /></Form.Item></Col>
              <Col xs={24} md={12}><Form.Item label="持续执行"><Space><Switch aria-label="持续执行" disabled={mode !== 'AUTO_DISCOVERY'} checked={continuous} onChange={setContinuous} /><Typography.Text className="muted">每轮仍必须等待人工评价</Typography.Text></Space></Form.Item></Col>
            </Row>
            <Button type="primary" htmlType="submit" loading={start.isPending}>启动任务</Button>
          </Form>
        </Card>
      )}
    </div>
  )
}
