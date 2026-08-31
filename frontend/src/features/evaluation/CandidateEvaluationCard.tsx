import { Card, Form, Input, Radio, Tag, Typography } from 'antd'
import { candidateFields } from './schema'
import { ScoreField } from './ScoreField'

export function CandidateEvaluationCard({ id, text, selected }: { id: string; text?: string; selected?: boolean }) {
  return <Card title={<span><Tag color={selected ? 'gold' : 'blue'}>{id}</Tag>{selected ? 'Agent 最终选择' : '候选'}</span>} className="candidate-card">
    <Typography.Paragraph className="candidate-copy">{text || '候选文案未能从运行记录中解析，请在任务详情检查 N12 原始输出。'}</Typography.Paragraph>
    <div className="score-grid">{candidateFields.map(([key,label]) => <ScoreField key={key} name={['candidates', id, key]} label={label}/>)}</div>
    <Form.Item name={['candidates', id, 'usability']} label="可用性" rules={[{required:true,message:'请选择可用性'}]}><Radio.Group options={[{label:'可用',value:'USABLE'},{label:'修改后可用',value:'USABLE_AFTER_EDIT'},{label:'不可用',value:'UNUSABLE'}]}/></Form.Item>
    <Form.Item name={['candidates', id, 'modification_advice']} label="修改建议" rules={[{required:true,message:'请填写修改建议；无建议可填“无”'}]}><Input.TextArea rows={2}/></Form.Item>
  </Card>
}
