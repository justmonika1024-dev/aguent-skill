import { Card, Collapse, Descriptions, Space, Tag, Typography } from 'antd'
import type { RunNode } from '../../api/types'
import { ArtifactView } from './ArtifactView'

export function NodeCard({ node }: { node: RunNode }) {
  const failed = node.status === 'FAILED' || Boolean(node.error_message)
  return (
    <Card className="node-card" size="small" title={<Space><Tag color={failed ? 'error' : 'processing'}>{node.node_key}</Tag><Typography.Text>{node.status ?? 'UNKNOWN'}</Typography.Text></Space>}>
      <Descriptions size="small" column={{ xs: 1, md: 3 }} items={[
        { key: 'attempt', label: '尝试', children: node.attempt_no ?? 1 },
        { key: 'branch', label: '分支', children: node.branch_id ?? '-' },
        { key: 'execution', label: '执行 ID', children: node.execution_id ?? '-' },
      ]} />
      {failed && <Typography.Text type="danger">{node.error_code}: {node.error_message}</Typography.Text>}
      <Collapse ghost items={[
        { key: 'output', label: '人可读输出', children: <ArtifactView value={node.output} /> },
        { key: 'input', label: '节点输入', children: <ArtifactView value={node.input} /> },
      ]} defaultActiveKey={['output']} />
    </Card>
  )
}
