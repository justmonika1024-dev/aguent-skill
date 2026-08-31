import { EyeOutlined, ReloadOutlined, SearchOutlined } from '@ant-design/icons'
import { useQuery } from '@tanstack/react-query'
import { Alert, Button, Input, Select, Space, Table, Tag, Typography } from 'antd'
import { useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { api } from '../api/client'
import { queryKeys } from '../api/queries'
import type { AdmissionMode, RunMode, RunSnapshot } from '../api/types'
import { RunStatus } from '../features/runs/RunStatus'

export function RunsPage() {
  const navigate=useNavigate(); const [search,setSearch]=useState(''); const [state,setState]=useState<string>(); const [mode,setMode]=useState<RunMode>(); const [admission,setAdmission]=useState<string>()
  const query=useQuery({queryKey:queryKeys.runs,queryFn:()=>api.get<RunSnapshot[]>('/runs')})
  const rows=useMemo(()=>(query.data??[]).filter(run=>(!state||run.state===state)&&(!mode||run.mode===mode)&&(!admission||run.admission_decision===admission)&&(!search||`${run.run_id}${run.seed_text??''}`.toLowerCase().includes(search.toLowerCase()))),[admission,mode,query.data,search,state])
  return <div className="page-stack">
    <div className="page-heading"><div><Typography.Title level={2}>运行历史</Typography.Title><Typography.Text className="muted">所有已落库任务均可通过持久化记录复盘</Typography.Text></div><Button icon={<ReloadOutlined/>} onClick={()=>query.refetch()}>刷新</Button></div>
    {query.error&&<Alert type="error" showIcon message="运行历史加载失败" description={(query.error as Error).message}/>}<Space wrap>
      <Input allowClear prefix={<SearchOutlined/>} placeholder="搜索 Run ID 或种子文案" value={search} onChange={event=>setSearch(event.target.value)}/>
      <Select allowClear placeholder="状态" value={state} onChange={setState} options={['RUNNING','WAITING_HUMAN_EVALUATION','COMPLETED','FAILED','TERMINATED'].map(value=>({label:value,value}))}/>
      <Select allowClear placeholder="运行模式" value={mode} onChange={setMode} options={[{label:'人工种子',value:'MANUAL_SEED'},{label:'自主发现',value:'AUTO_DISCOVERY'}]}/>
      <Select allowClear placeholder="准入决定" value={admission} onChange={setAdmission} options={['ADMIT','NOT_ADMIT'].map(value=>({label:value,value}))}/>
    </Space>
    <Table rowKey="run_id" loading={query.isLoading} dataSource={rows} scroll={{x:900}} columns={[
      {title:'任务',dataIndex:'run_id',render:(value:string,run:RunSnapshot)=><Space direction="vertical" size={0}><Typography.Text strong>{run.seed_text||'自主发现'}</Typography.Text><Typography.Text type="secondary" copyable>{value}</Typography.Text></Space>},
      {title:'模式',dataIndex:'mode',render:(value:RunMode)=><Tag>{value==='MANUAL_SEED'?'人工种子':'自主发现'}</Tag>},
      {title:'状态',dataIndex:'state',render:value=><RunStatus state={value}/>},
      {title:'准入模式',dataIndex:'admission_mode',render:(value:AdmissionMode)=>value??'-'},
      {title:'准入决定',dataIndex:'admission_decision',render:value=>value??'-'}, {title:'正式梗',dataIndex:'formal_meme_id',render:value=>value??'-'},
      {title:'操作',render:(_,run)=><Button icon={<EyeOutlined/>} onClick={()=>navigate(`/runs/${run.run_id}`)}>查看</Button>},
    ]}/>
  </div>
}
