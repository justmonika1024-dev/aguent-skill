import { Form, Radio } from 'antd'
import type { NamePath } from 'antd/es/form/interface'

export function ScoreField({ name, label }: { name: NamePath; label: string }) {
  return <Form.Item name={name} label={label} rules={[{ required: true, message: `请评价${label}` }]}><Radio.Group optionType="button" buttonStyle="solid" options={[1,2,3,4,5].map(value=>({label:String(value),value}))} /></Form.Item>
}
