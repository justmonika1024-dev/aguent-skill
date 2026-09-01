import { Card, Form, Input, Typography } from 'antd'
import type { NamePath } from 'antd/es/form/interface'
import type { ReactNode } from 'react'
import { RunArtifactSummary, type ArtifactBranch, type ArtifactNode } from './RunArtifactSummary'
import { ScoreField } from './ScoreField'

export type EvaluationMetricField = readonly [key: string, label: string]

function nestedName(path: NamePath, field: string): NamePath {
  return [...(Array.isArray(path) ? path : [path]), field]
}

export interface EvaluationModuleCardProps {
  title: string
  description: string
  nodes: readonly ArtifactNode[]
  nodeKeys: readonly string[]
  activeBranchId: string
  branches?: readonly ArtifactBranch[]
  fields: readonly EvaluationMetricField[]
  formPath: NamePath
  commentLabel?: string
  children?: ReactNode
}

export function EvaluationModuleCard({
  title,
  description,
  nodes,
  nodeKeys,
  activeBranchId,
  branches,
  fields,
  formPath,
  commentLabel = '模块意见（选填）',
  children,
}: EvaluationModuleCardProps) {
  return <Card title={title} className="surface evaluation-module-card">
    <Typography.Paragraph type="secondary">{description}</Typography.Paragraph>
    <RunArtifactSummary nodes={nodes} nodeKeys={nodeKeys} activeBranchId={activeBranchId} branches={branches} />
    {children}
    <div className="score-grid">{fields.map(([key, label]) => <ScoreField
      key={key}
      name={nestedName(formPath, key)}
      label={label}
    />)}</div>
    <Form.Item name={nestedName(formPath, 'comment')} label={commentLabel} initialValue="">
      <Input.TextArea rows={2} />
    </Form.Item>
  </Card>
}
