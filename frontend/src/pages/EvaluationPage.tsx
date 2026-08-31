import { ArrowLeftOutlined, SendOutlined } from '@ant-design/icons'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { Alert, Button, Card, Form, Input, Radio, Select, Space, Spin, Typography, message } from 'antd'
import { useMemo, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { api, ApiError } from '../api/client'
import { queryKeys } from '../api/queries'
import { CandidateEvaluationCard } from '../features/evaluation/CandidateEvaluationCard'
import { ArtifactView } from '../features/runs/ArtifactView'
import { ScoreField } from '../features/evaluation/ScoreField'
import { buildEvaluationPayload, candidateArtifacts, candidateIds, candidateSetFields, finalFields, processingFields, selectedCandidateId, type EvaluationFormValues } from '../features/evaluation/schema'
import { useRunRecord, useRunSnapshot } from '../features/runs/runApi'

export function EvaluationPage() {
  const { runId = '' } = useParams(); const navigate = useNavigate(); const queryClient = useQueryClient()
  const [form] = Form.useForm<EvaluationFormValues>(); const [complete, setComplete] = useState(false); const [apiMessage, contextHolder] = message.useMessage()
  const record = useRunRecord(runId); const snapshot = useRunSnapshot(runId)
  const candidates = useMemo(() => candidateArtifacts(record.data?.nodes ?? []), [record.data?.nodes])
  const selected = useMemo(() => selectedCandidateId(record.data?.nodes ?? []), [record.data?.nodes])
  const artifact = (nodeKey:string) => record.data?.nodes.filter(node=>node.node_key===nodeKey).at(-1)?.output
  const mode = snapshot.data?.admission_mode ?? record.data?.run.admission_mode ?? 'HUMAN'
  const submit = useMutation({ mutationFn:(values:EvaluationFormValues) => api.post(`/runs/${runId}/evaluation`, buildEvaluationPayload(values, mode, snapshot.data!.run_version!, snapshot.data!.active_branch_id ?? record.data!.run.active_branch_id!)), onSuccess:async()=>{ await apiMessage.success('评价已提交，反馈将影响下一轮策略'); await queryClient.invalidateQueries({queryKey:queryKeys.runRecord(runId)}); navigate(`/runs/${runId}`) } })
  const conflict = submit.error instanceof ApiError && submit.error.code === 'RUN_VERSION_CONFLICT'
  const revalidate = () => void form.validateFields({validateOnly:true}).then(()=>setComplete(true)).catch(()=>setComplete(false))
  if (record.isLoading || snapshot.isLoading) return <Spin tip="加载评价材料"><div className="loading-space"/></Spin>
  if (!record.data || !snapshot.data) return <Alert type="error" message="无法加载评价材料" description={(record.error as Error)?.message ?? (snapshot.error as Error)?.message}/>
  if (snapshot.data.state !== 'WAITING_HUMAN_EVALUATION') return <Alert type="warning" showIcon message="当前任务不在等待评价状态" action={<Button onClick={()=>navigate(`/runs/${runId}`)}>返回详情</Button>}/>
  return <div className="page-stack">{contextHolder}<div className="page-heading"><div><Button type="link" icon={<ArrowLeftOutlined/>} onClick={()=>navigate(`/runs/${runId}`)}>返回详情</Button><Typography.Title level={2}>人工结构化评价</Typography.Title><Typography.Text className="muted">评价是流程必经节点；提交后是否自动开启下一轮由持续执行开关决定。</Typography.Text></div></div>
    {submit.error && <Alert type="error" message={conflict?'任务版本已变化':'提交失败'} description={conflict?'请刷新评价材料后重新确认，当前填写内容仍保留。':(submit.error as Error).message} action={conflict?<Button onClick={()=>{void snapshot.refetch();void record.refetch()}}>刷新材料</Button>:undefined}/>}<Card title="Agent 生成与选择依据" className="surface"><Typography.Title level={5}>N13 候选自评分</Typography.Title><ArtifactView value={artifact('N13')}/><Typography.Title level={5}>N14 最终选择</Typography.Title><ArtifactView value={artifact('N14')}/><Typography.Title level={5}>N15 正式包装</Typography.Title><ArtifactView value={artifact('N15')}/></Card><Form form={form} layout="vertical" onFieldsChange={revalidate} onFinish={(v)=>submit.mutate(v)}>
      <Card title="1. 处理链评价" className="surface"><div className="score-grid">{processingFields.map(([k,l])=><ScoreField key={k} name={['processing_chain',k]} label={l}/>)}</div><Form.Item name={['processing_chain','comment']} label="处理链意见" rules={[{required:true,message:'无意见可填“无”'}]}><Input.TextArea/></Form.Item></Card>
      <Card title="2. 候选集整体评价" className="surface"><div className="score-grid">{candidateSetFields.map(([k,l])=><ScoreField key={k} name={['candidate_set',k]} label={l}/>)}</div><Form.Item name={['candidate_set','comment']} label="候选集意见" rules={[{required:true,message:'无意见可填“无”'}]}><Input.TextArea/></Form.Item></Card>
      <div className="card-list">{candidateIds.map(id=>{const item=candidates.find(c=>c.candidate_id===id); return <CandidateEvaluationCard key={id} id={id} text={typeof item?.text==='string'?item.text:undefined} selected={selected===id}/>})}</div>
      <Card title="3. 最终结果评价" className="surface"><Form.Item name={['final_result','is_best_candidate']} label={`${selected ?? 'Agent 所选候选'} 是否最佳`} rules={[{required:true,message:'请选择'}]}><Radio.Group options={[{label:'是',value:true},{label:'否',value:false}]}/></Form.Item><Form.Item noStyle shouldUpdate={(a,b)=>a.final_result?.is_best_candidate!==b.final_result?.is_best_candidate}>{({getFieldValue})=>getFieldValue(['final_result','is_best_candidate'])===false&&<Form.Item name={['final_result','better_candidate_id']} label="更合适候选"><Select allowClear options={candidateIds.map(id=>({label:id,value:id}))}/></Form.Item>}</Form.Item><div className="score-grid">{finalFields.map(([k,l])=><ScoreField key={k} name={['final_result',k]} label={l}/>)}</div><Form.Item name={['final_result','comment']} label="最终结果意见" rules={[{required:true,message:'无意见可填“无”'}]}><Input.TextArea/></Form.Item></Card>
      <Card title="4. 问题定位与准入" className="surface"><Form.Item name="main_problem_nodes" label="主要问题节点" getValueFromEvent={(values:string[])=>values.includes('NO_OBVIOUS_PROBLEM')?['NO_OBVIOUS_PROBLEM']:values} rules={[{required:true,message:'至少选择一项'}]}><Select mode="multiple" options={[...Array.from({length:16},(_,i)=>`N${String(i+2).padStart(2,'0')}`),'NO_OBVIOUS_PROBLEM'].map(v=>({label:v==='NO_OBVIOUS_PROBLEM'?'无明显问题':v,value:v}))}/></Form.Item>{mode==='HUMAN'?<Form.Item name={['admission','decision']} label="入库决定" rules={[{required:true,message:'请选择'}]}><Radio.Group options={[{label:'入库',value:'ADMIT'},{label:'不入库',value:'NOT_ADMIT'}]}/></Form.Item>:<Form.Item name={['admission','override']} label="自动准入复核" rules={[{required:true,message:'请选择'}]}><Radio.Group options={[{label:'保持 Agent 决定',value:'KEEP'},{label:'改为入库',value:'OVERRIDE_TO_ADMIT'},{label:'改为不入库',value:'OVERRIDE_TO_NOT_ADMIT'}]}/></Form.Item>}<Form.Item name={['admission','reason']} label="准入理由" rules={[{required:true,message:'请填写理由'}]}><Input.TextArea/></Form.Item><Form.Item name="overall_comment" label="总体意见" rules={[{required:true,message:'无意见可填“无”'}]}><Input.TextArea/></Form.Item></Card>
      <div className="sticky-submit"><Space><Typography.Text type="secondary">所有结构化字段填写完成后方可提交</Typography.Text><Button aria-label="提交评价" type="primary" htmlType="submit" icon={<SendOutlined/>} disabled={!complete} loading={submit.isPending}>提交评价</Button></Space></div>
    </Form>
  </div>
}
