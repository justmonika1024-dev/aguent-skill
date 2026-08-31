import { CopyOutlined, EyeOutlined, SearchOutlined } from '@ant-design/icons'
import { useQuery } from '@tanstack/react-query'
import { Alert, Button, Input, Space, Table, Tag, Tooltip, Typography, message } from 'antd'
import { useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { api } from '../api/client'
import { queryKeys } from '../api/queries'
import type { MemeRecord } from '../api/types'

export function MemesPage() {
  const navigate=useNavigate(); const [search,setSearch]=useState(''); const [toast,holder]=message.useMessage()
  const query=useQuery({queryKey:queryKeys.memes,queryFn:()=>api.get<MemeRecord[]>('/memes')})
  const rows=useMemo(()=>(query.data??[]).filter(meme=>`${meme.title}${meme.original_meme_text}${meme.final_agu_text}`.includes(search)),[query.data,search])
  const copy=(text:string)=>void navigator.clipboard.writeText(text).then(()=>toast.success('已复制')).catch(()=>toast.error('复制失败，请手动复制'))
  return <div className="page-stack">{holder}
    <div className="page-heading"><div><Typography.Title level={2}>正式梗库</Typography.Title><Typography.Text className="muted">仅展示已通过准入并持久化的正式文案</Typography.Text></div></div>
    {query.error&&<Alert type="error" showIcon message="正式梗库加载失败" description={(query.error as Error).message}/>}<Input allowClear prefix={<SearchOutlined/>} placeholder="搜索标题、原梗或文案" value={search} onChange={event=>setSearch(event.target.value)} style={{maxWidth:360}}/>
    <Table rowKey="id" loading={query.isLoading} dataSource={rows} scroll={{x:900}} columns={[
      {title:'标题',dataIndex:'title',render:(value:string)=><Typography.Text strong>{value}</Typography.Text>}, {title:'正式文案',dataIndex:'final_agu_text',ellipsis:true},
      {title:'状态',dataIndex:'status',render:value=><Tag color="green">{value}</Tag>}, {title:'来源任务',dataIndex:'source_run_id'},
      {title:'操作',render:(_,meme)=><Space><Button icon={<EyeOutlined/>} onClick={()=>navigate(`/memes/${meme.id}`)}>详情</Button><Button aria-label="复制文案" icon={<CopyOutlined/>} onClick={()=>copy(meme.final_agu_text)}/><Tooltip title="MVP 后端尚未开放下架接口"><Button aria-label="下架" disabled>下架</Button></Tooltip></Space>},
    ]}/>
  </div>
}
