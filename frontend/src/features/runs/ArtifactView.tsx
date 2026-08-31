import { Empty, Typography } from 'antd'
import type { JsonValue } from '../../api/types'

export function ArtifactView({ value }: { value?: JsonValue }) {
  if (value === undefined || value === null) return <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="无结构化输出" />
  if (typeof value === 'string') return <Typography.Paragraph className="artifact-text" copyable>{value}</Typography.Paragraph>
  return <pre className="code-block">{JSON.stringify(value, null, 2)}</pre>
}
