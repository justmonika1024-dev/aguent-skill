import { ExportOutlined } from '@ant-design/icons'
import { Card, Space, Tag, Typography } from 'antd'
import type { SourceEvidence as Source } from '../../api/types'

export function SourceEvidence({ source }: { source: Source }) {
  return (
    <Card size="small" className="source-card">
      <Space direction="vertical" size={6} style={{ width: '100%' }}>
        <Space wrap><Tag color="cyan">{source.evidence_type}</Tag><Tag>{source.provider ?? 'unknown'}</Tag><Tag>{source.content_status ?? 'unknown'}</Tag></Space>
        <Typography.Text strong>{source.title || source.source_id}</Typography.Text>
        {source.text && <Typography.Paragraph ellipsis={{ rows: 4, expandable: true }}>{source.text}</Typography.Paragraph>}
        {source.url && <Typography.Link href={source.url} target="_blank" rel="noreferrer">打开来源 <ExportOutlined /></Typography.Link>}
      </Space>
    </Card>
  )
}
