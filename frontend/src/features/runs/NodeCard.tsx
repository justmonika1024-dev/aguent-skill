import { Card, Collapse, Descriptions, Space, Tag, Typography } from 'antd'
import type { RunNode } from '../../api/types'
import { ArtifactView } from './ArtifactView'
import { getNodeMetadata } from './nodeMetadata'

export function NodeCard({ node }: { node: RunNode }) {
  const failed = node.status === 'FAILED' || Boolean(node.error_message)
  const metadata = getNodeMetadata(node.node_key)
  return (
    <Card className="node-card" size="small" title={<Space wrap><Tag color={failed ? 'error' : 'processing'}>{node.node_key}</Tag><Typography.Text strong>{metadata.name}</Typography.Text><Typography.Text type="secondary">{node.status ?? 'UNKNOWN'}</Typography.Text></Space>}>
      <Typography.Paragraph type="secondary">{metadata.responsibility}</Typography.Paragraph>
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
