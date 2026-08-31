import { ApiOutlined, CheckCircleOutlined, CloseCircleOutlined, SaveOutlined } from '@ant-design/icons'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Alert, Button, Card, Descriptions, Form, InputNumber, Space, Spin, Tag, Typography, message } from 'antd'
import { api } from '../api/client'
import { queryKeys } from '../api/queries'
import type { SystemConfig } from '../api/types'

type Runtime = { values: Record<string, number> }
type Probe = { ok: boolean; provider?: string; message?: string; error?: string }

async function testConnection(kind:'llm'|'search') {
  const result = await api.post<Probe>(`/system/connection-tests/${kind}`)
  if (!result.ok) throw new Error(result.error ?? result.message ?? `${kind} 连接失败`)
  return result
}

export function SettingsPage() {
  const queryClient = useQueryClient(); const [form] = Form.useForm(); const [toast, holder] = message.useMessage()
  const config = useQuery({queryKey:queryKeys.config,queryFn:()=>api.get<SystemConfig>('/system/config')})
  const runtime = useQuery({queryKey:queryKeys.runtimeParameters,queryFn:()=>api.get<Runtime>('/system/runtime-parameters')})
  const patch = useMutation({mutationFn:(values:Record<string,number>)=>api.patch<Runtime>('/system/runtime-parameters',{values}),onSuccess:async()=>{await queryClient.invalidateQueries({queryKey:queryKeys.runtimeParameters});void toast.success('运行参数已保存')}})
  const probe = useMutation({mutationFn:testConnection,onSuccess:r=>void toast.success(`${r.provider??'服务'}连接成功`),onError:e=>void toast.error((e as Error).message)})
  if (config.isLoading || runtime.isLoading) return <Spin />
  if (config.error || runtime.error) return <Alert type="error" showIcon message="设置加载失败" description={(config.error as Error)?.message ?? (runtime.error as Error)?.message}/>
  return <div className="page-stack">{holder}
    <div className="page-heading"><div><Typography.Title level={2}>设置</Typography.Title><Typography.Text className="muted">模型、Base URL 与密钥只允许在启动前通过 .env 配置</Typography.Text></div></div>
    <Alert type="warning" showIcon message="页面不会读取或显示 API Key" description="启动后只能修改工作流运行参数和执行连接测试。"/>
    <Card title="启动配置" className="surface"><Descriptions column={{xs:1,md:2}} items={[
      {key:'provider',label:'LLM Provider',children:config.data?.llm_provider}, {key:'model',label:'模型',children:config.data?.llm_model},
      {key:'llmkey',label:'LLM Key',children:<Tag icon={config.data?.api_key_configured?<CheckCircleOutlined/>:<CloseCircleOutlined/>} color={config.data?.api_key_configured?'success':'error'}>{config.data?.api_key_configured?'已配置':'未配置'}</Tag>},
      {key:'searchkey',label:'Exa Key',children:<Tag icon={config.data?.search_api_key_configured?<CheckCircleOutlined/>:<CloseCircleOutlined/>} color={config.data?.search_api_key_configured?'success':'error'}>{config.data?.search_api_key_configured?'已配置':'未配置'}</Tag>},
    ]}/><Space><Button icon={<ApiOutlined/>} loading={probe.isPending} onClick={()=>probe.mutate('llm')}>测试 LLM</Button><Button icon={<ApiOutlined/>} loading={probe.isPending} onClick={()=>probe.mutate('search')}>测试 Exa</Button></Space></Card>
    <Card title="运行参数" className="surface"><Form form={form} layout="vertical" initialValues={runtime.data?.values} onFinish={values=>patch.mutate(values)}><div className="score-grid">{Object.keys(runtime.data?.values??{}).map(key=><Form.Item key={key} name={key} label={key} rules={[{required:true},{type:'number',min:1}]}><InputNumber min={1} style={{width:'100%'}}/></Form.Item>)}</div><Button type="primary" htmlType="submit" icon={<SaveOutlined/>} loading={patch.isPending}>保存参数</Button></Form></Card>
  </div>
}
