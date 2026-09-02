import { ArrowLeftOutlined, FormOutlined, ReloadOutlined, RedoOutlined } from '@ant-design/icons'
import { useMutation } from '@tanstack/react-query'
import { Alert, Button, Card, Col, Descriptions, Empty, Row, Space, Spin, Statistic, Table, Tabs, Tag, Timeline, Typography } from 'antd'
import { useNavigate, useParams } from 'react-router-dom'
import { NodeCard } from '../features/runs/NodeCard'
import { getNodeMetadata, humanizeNodeError, retryGuidance } from '../features/runs/nodeMetadata'
import { RunStatus } from '../features/runs/RunStatus'
import { SourceEvidence } from '../features/runs/SourceEvidence'
import { sendRunCommand, useRunRecord, useRunUsage } from '../features/runs/runApi'
import { useRunSnapshot } from '../features/runs/runApi'
import { useRunEvents } from '../features/runs/useRunEvents'

export function RunDetailPage() {
  const { runId = '' } = useParams()
  const navigate = useNavigate()
  const snapshot = useRunSnapshot(runId)
  const realtime = snapshot.data?.run_version !== undefined && !['COMPLETED','FAILED','TERMINATED'].includes(snapshot.data.state)
  const record = useRunRecord(runId, realtime)
  const usage = useRunUsage(runId)
  const retry = useMutation({
    mutationFn: ({ nodeKey, runVersion }: { nodeKey: string; runVersion: number }) =>
      sendRunCommand(runId, 'RETRY_NODE', runVersion, { node_key: nodeKey }),
    onSuccess: async () => {
      await Promise.all([snapshot.refetch(), record.refetch(), usage.refetch()])
    },
  })
  useRunEvents(realtime ? runId : undefined)
  if (record.isLoading) return <Spin tip="加载运行记录"><div className="loading-space" /></Spin>
  if (record.error || !record.data) return <Alert type="error" showIcon message="无法加载运行记录" description={(record.error as Error)?.message} action={<Button onClick={() => record.refetch()} icon={<ReloadOutlined />}>重试</Button>} />
  const data = record.data
  const liveRun = snapshot.data ?? data.run
  const failedNode = [...data.nodes].reverse().find(node => node.status === 'FAILED' || Boolean(node.error_message))
  const failedEvent = [...data.events].reverse().find(event => event.event_type === 'node.failed')
  const failedNodeKey = failedNode?.node_key
    ?? (typeof failedEvent?.payload.node_key === 'string' ? failedEvent.payload.node_key : liveRun.current_node)
  const rawFailure = failedNode?.error_message
    ?? (typeof failedEvent?.payload.error === 'string' ? failedEvent.payload.error : undefined)
  const failureCode = failedNode?.error_code
    ?? (typeof failedEvent?.payload.error_code === 'string' ? failedEvent.payload.error_code : undefined)
  const failureMetadata = failedNodeKey ? getNodeMetadata(failedNodeKey) : undefined
  const canRetry = liveRun.state === 'FAILED'
    && typeof snapshot.data?.run_version === 'number'
    && snapshot.data.retry_available !== false
    && Boolean(failedNodeKey)
  return <div className="page-stack">
    <div className="page-heading"><div><Button type="link" icon={<ArrowLeftOutlined />} onClick={() => navigate('/runs')}>返回历史</Button><Typography.Title level={2}>任务详情</Typography.Title><Typography.Text className="muted">{data.run.run_id}</Typography.Text></div><Space><RunStatus state={liveRun.state} />{liveRun.state === 'WAITING_HUMAN_EVALUATION' && <Button type="primary" icon={<FormOutlined />} onClick={() => navigate(`/runs/${runId}/evaluation`)}>人工评价</Button>}</Space></div>
    {liveRun.state === 'FAILED' && failedNodeKey && (failedNode || failedEvent) && <Alert
      type="error"
      showIcon
      message={`${failedNodeKey} ${failureMetadata?.name ?? '节点'}失败`}
      description={<Space direction="vertical" size={6}>
        <Typography.Text>{humanizeNodeError(rawFailure ?? '', failureCode)}</Typography.Text>
        <Typography.Text><strong>重试建议：</strong>{retryGuidance(failedNodeKey)}</Typography.Text>
        <Typography.Text type="secondary"><strong>技术错误：</strong>{rawFailure || failureCode || '未提供'}</Typography.Text>
        {!canRetry && <Typography.Text type="warning">当前服务中已无该任务的内存状态，无法原地重试；请使用原种子新建一轮任务。</Typography.Text>}
        {retry.error && <Typography.Text type="danger">{(retry.error as Error).message}</Typography.Text>}
      </Space>}
      action={canRetry ? <Button
        danger
        icon={<RedoOutlined />}
        loading={retry.isPending}
        onClick={() => retry.mutate({ nodeKey: failedNodeKey, runVersion: snapshot.data!.run_version! })}
      >从 {failedNodeKey} 重试</Button> : undefined}
    />}
    <Card className="surface"><Descriptions column={{ xs: 1, md: 2, xl: 4 }} items={[
      { key: 'mode', label: '模式', children: data.run.mode === 'MANUAL_SEED' ? '人工种子' : '自主发现' },
      { key: 'admission', label: '准入模式', children: data.run.admission_mode ?? '-' },
      { key: 'branch', label: '活动分支', children: data.run.active_branch_id ?? '-' },
      { key: 'decision', label: '准入决定', children: data.run.admission_decision ?? '-' },
      { key: 'seed', label: '种子/原始输入', children: data.run.seed_text ?? '自主发现' },
    ]} /></Card>
    <Row gutter={[16,16]}><Col xs={12} lg={6}><Card><Statistic title="节点执行" value={data.nodes.length}/></Card></Col><Col xs={12} lg={6}><Card><Statistic title="来源证据" value={data.sources.length}/></Card></Col><Col xs={12} lg={6}><Card><Statistic title="API 调用" value={usage.data?.calls ?? data.api_calls.length}/></Card></Col><Col xs={12} lg={6}><Card><Statistic title="Token" value={usage.data?.total_tokens ?? 0}/></Card></Col></Row>
    <Tabs items={[
      { key: 'nodes', label: `处理链 (${data.nodes.length})`, children: <div className="card-list">{data.nodes.length ? data.nodes.map((node, i) => <NodeCard key={node.execution_id ?? `${node.node_key}-${i}`} node={node}/>) : <Empty description="尚无节点输出"/>}</div> },
      { key: 'sources', label: `来源与变式 (${data.sources.length})`, children: <div className="card-grid">{data.sources.length ? data.sources.map((source, i) => <SourceEvidence key={source.evidence_id ?? `${source.source_id}-${i}`} source={source}/>) : <Empty description="尚无来源证据"/>}</div> },
      { key: 'events', label: `状态事件 (${data.events.length})`, children: data.events.length ? <Timeline items={data.events.map(event => ({ color: event.event_type.includes('failed') ? 'red' : 'blue', children: <Space direction="vertical" size={0}><Typography.Text strong>{event.sequence}. {event.event_type}</Typography.Text><Typography.Text type="secondary">{event.state} · {event.occurred_at}</Typography.Text></Space> }))}/> : <Empty/> },
      { key: 'api', label: `API 消耗 (${data.api_calls.length})`, children: <Table rowKey="call_id" pagination={false} scroll={{x:700}} dataSource={data.api_calls} columns={[
        { title:'节点', dataIndex:'node_key' }, { title:'类型', dataIndex:'api_type', render:(v:string)=><Tag color={v==='llm'?'purple':'cyan'}>{v}</Tag> }, { title:'提供商', dataIndex:'provider' }, { title:'模型', dataIndex:'model' }, { title:'Token', dataIndex:'total_tokens' }, { title:'成本($)', dataIndex:'cost_usd' }, { title:'延迟(ms)', dataIndex:'latency_ms' }, { title:'状态', dataIndex:'status' },
      ]}/> },
      { key: 'branches', label: `分支 (${data.branches.length})`, children: <Table pagination={false} dataSource={data.branches} rowKey={(row) => String(row.branch_id)} columns={Object.keys(data.branches[0] ?? {}).map(key => ({ title:key, dataIndex:key }))}/> },
    ]}/>
  </div>
}
