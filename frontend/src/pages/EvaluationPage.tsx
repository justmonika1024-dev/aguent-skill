import { ArrowLeftOutlined, SendOutlined } from '@ant-design/icons'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { Alert, Button, Card, Form, Input, Radio, Select, Space, Spin, Typography, message } from 'antd'
import { useNavigate, useParams } from 'react-router-dom'
import { api, ApiError } from '../api/client'
import { queryKeys } from '../api/queries'
import { CandidateEvaluationCard } from '../features/evaluation/CandidateEvaluationCard'
import { EvaluationModuleCard } from '../features/evaluation/EvaluationModuleCard'
import { latestNodeArtifact } from '../features/evaluation/RunArtifactSummary'
import {
  buildEvaluationPayload,
  candidateArtifacts,
  candidateIds,
  candidateSetFields,
  finalFields,
  originalSearchPlanFields,
  selectedCandidateId,
  selectedOriginalMemeFields,
  templateExtractionFields,
  variantSearchPlanFields,
  variantSearchResultsFields,
  type EvaluationFormValues,
} from '../features/evaluation/schema'
import { useRunRecord, useRunSnapshot } from '../features/runs/runApi'

const problemNodeOptions = [
  ...Array.from({ length: 16 }, (_, index) => `N${String(index + 2).padStart(2, '0')}`),
  'NO_OBVIOUS_PROBLEM',
].map((value) => ({
  label: value === 'NO_OBVIOUS_PROBLEM' ? '无明显问题' : value,
  value,
}))

export function EvaluationPage() {
  const { runId = '' } = useParams()
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const [form] = Form.useForm<EvaluationFormValues>()
  const [apiMessage, contextHolder] = message.useMessage()
  const record = useRunRecord(runId)
  const snapshot = useRunSnapshot(runId)
  const activeBranchId = snapshot.data?.active_branch_id ?? record.data?.run.active_branch_id ?? ''
  const nodes = record.data?.nodes ?? []
  const branches = record.data?.branches ?? []

  const candidateArtifact = latestNodeArtifact(nodes, 'N12', activeBranchId, branches)
  const selectionArtifact = latestNodeArtifact(nodes, 'N14', activeBranchId, branches)
  const candidates = candidateArtifacts([{ node_key: 'N12', output: candidateArtifact }])
  const selected = selectedCandidateId([{ node_key: 'N14', output: selectionArtifact }])
  const mode = snapshot.data?.admission_mode ?? record.data?.run.admission_mode ?? 'HUMAN'

  const submit = useMutation({
    mutationFn: (values: EvaluationFormValues) => api.post(
      `/runs/${runId}/evaluation`,
      buildEvaluationPayload(
        values,
        mode,
        snapshot.data!.run_version!,
        activeBranchId,
      ),
    ),
    onSuccess: async () => {
      await apiMessage.success('评价已提交，反馈将影响下一轮策略')
      await queryClient.invalidateQueries({ queryKey: queryKeys.runRecord(runId) })
      navigate(`/runs/${runId}`)
    },
  })

  const submitError = submit.error instanceof ApiError ? submit.error : undefined
  const conflict = submitError?.status === 409 || submitError?.code === 'RUN_VERSION_CONFLICT'
  const submitErrorTitle = conflict
    ? '任务版本已变化（HTTP 409）'
    : submitError?.status === 422
      ? '评价内容未通过校验（HTTP 422）'
      : '提交失败'

  const handleFinish = (values: EvaluationFormValues) => {
    const finalResult = values.final_result
    if (
      finalResult.is_best_candidate === false
      && !finalResult.better_candidate_id
      && !finalResult.comment?.trim()
    ) {
      form.setFields([{
        name: ['final_result', 'comment'],
        errors: ['未选择更合适候选时，请说明最终结果的问题'],
      }])
      return
    }
    form.setFields([{ name: ['final_result', 'comment'], errors: [] }])
    submit.mutate(values)
  }

  const normalizeProblemNodes = (values: string[]) => {
    const previous = form.getFieldValue('main_problem_nodes') ?? []
    const addedNoProblem = values.includes('NO_OBVIOUS_PROBLEM') && !previous.includes('NO_OBVIOUS_PROBLEM')
    if (addedNoProblem) return ['NO_OBVIOUS_PROBLEM']
    if (previous.includes('NO_OBVIOUS_PROBLEM')) return values.filter((value) => value !== 'NO_OBVIOUS_PROBLEM')
    return values
  }

  if (record.isLoading || snapshot.isLoading) {
    return <Spin tip="加载评价材料"><div className="loading-space" /></Spin>
  }
  if (!record.data || !snapshot.data) {
    return <Alert
      type="error"
      message="无法加载评价材料"
      description={(record.error as Error)?.message ?? (snapshot.error as Error)?.message}
    />
  }
  if (snapshot.data.state !== 'WAITING_HUMAN_EVALUATION') {
    return <Alert
      type="warning"
      showIcon
      message="当前任务不在等待评价状态"
      action={<Button onClick={() => navigate(`/runs/${runId}`)}>返回详情</Button>}
    />
  }

  return <div className="page-stack evaluation-page">
    {contextHolder}
    <div className="page-heading">
      <div>
        <Button type="link" icon={<ArrowLeftOutlined />} onClick={() => navigate(`/runs/${runId}`)}>返回详情</Button>
        <Typography.Title level={2}>人工结构化评价</Typography.Title>
        <Typography.Text className="muted">评价是流程必经节点；提交后是否自动开启下一轮由持续执行开关决定。</Typography.Text>
      </div>
    </div>

    {submit.error && <Alert
      type="error"
      showIcon
      message={submitErrorTitle}
      description={conflict
        ? '请刷新评价材料后重新确认，当前填写内容仍保留。'
        : (submit.error as Error).message}
      action={conflict
        ? <Button onClick={() => { void snapshot.refetch(); void record.refetch() }}>刷新材料</Button>
        : undefined}
    />}

    <Form form={form} className="evaluation-form" layout="vertical" onFinish={handleFinish}>
      <EvaluationModuleCard
        title="原始梗搜索计划"
        description="查看原始梗查询计划和搜索证据，评价搜索方向是否准确、完整。"
        nodes={nodes}
        nodeKeys={['N03', 'N04']}
        activeBranchId={activeBranchId}
        branches={branches}
        fields={originalSearchPlanFields}
        formPath="original_search_plan"
      />

      <EvaluationModuleCard
        title="最终选定原始梗"
        description="查看 Agent 最终选定的原始梗，评价其传播基础、适用性和证据可靠性。"
        nodes={nodes}
        nodeKeys={['N05']}
        activeBranchId={activeBranchId}
        branches={branches}
        fields={selectedOriginalMemeFields}
        formPath="selected_original_meme"
      />

      <EvaluationModuleCard
        title="变式搜索计划"
        description="查看变式检索查询，评价槽位替换导向、查询多样性和噪声规避。"
        nodes={nodes}
        nodeKeys={['N07']}
        activeBranchId={activeBranchId}
        branches={branches}
        fields={variantSearchPlanFields}
        formPath="variant_search_plan"
      />

      <EvaluationModuleCard
        title="最终变式搜索结果"
        description="查看搜索证据和筛选后的真实变式，评价结果质量与多样性。"
        nodes={nodes}
        nodeKeys={['N08', 'N09']}
        activeBranchId={activeBranchId}
        branches={branches}
        fields={variantSearchResultsFields}
        formPath="variant_search_results"
      />

      <EvaluationModuleCard
        title="模板提取结果"
        description="查看提取模板及校验结果，评价原句重建、变式覆盖和槽位合理性。"
        nodes={nodes}
        nodeKeys={['N10', 'N11']}
        activeBranchId={activeBranchId}
        branches={branches}
        fields={templateExtractionFields}
        formPath="template_extraction"
      />

      <EvaluationModuleCard
        title="正式梗生成候选"
        description="先查看 N12 候选文案和 N13 Agent 自评分，再逐条给出人工评分与可用性。"
        nodes={nodes}
        nodeKeys={['N12', 'N13']}
        activeBranchId={activeBranchId}
        branches={branches}
        fields={candidateSetFields}
        formPath={['candidate_generation', 'overall']}
        commentLabel="候选集整体意见（选填）"
      >
        <div className="card-list candidate-evaluation-list">
          {candidateIds.map((id) => {
            const candidate = candidates.find((item) => item.candidate_id === id)
            return <CandidateEvaluationCard
              key={id}
              id={id}
              text={typeof candidate?.text === 'string' ? candidate.text : undefined}
              selected={selected === id}
            />
          })}
        </div>
      </EvaluationModuleCard>

      <EvaluationModuleCard
        title="最终正式梗结果"
        description="查看 N14 最终选择与 N15 正式文案，确认 Agent 选择并评价最终结果。"
        nodes={nodes}
        nodeKeys={['N14', 'N15']}
        activeBranchId={activeBranchId}
        branches={branches}
        fields={finalFields}
        formPath="final_result"
        commentLabel="最终结果意见（选填）"
      >
        <Form.Item
          name={['final_result', 'is_best_candidate']}
          label={`${selected ?? 'Agent 所选候选'} 是否最佳`}
          rules={[{ required: true, message: '请选择最终候选是否最佳' }]}
        >
          <Radio.Group options={[{ label: '是', value: true }, { label: '否', value: false }]} />
        </Form.Item>
        <Form.Item
          noStyle
          shouldUpdate={(previous, current) => (
            previous.final_result?.is_best_candidate !== current.final_result?.is_best_candidate
          )}
        >
          {({ getFieldValue }) => getFieldValue(['final_result', 'is_best_candidate']) === false
            ? <Form.Item name={['final_result', 'better_candidate_id']} label="更合适候选（选填）">
              <Select allowClear options={candidateIds.map((id) => ({ label: id, value: id }))} />
            </Form.Item>
            : null}
        </Form.Item>
      </EvaluationModuleCard>

      <Card title="问题定位与准入" className="surface evaluation-decision-card">
        <Form.Item
          name="main_problem_nodes"
          label="主要问题节点"
          getValueFromEvent={normalizeProblemNodes}
          rules={[{ required: true, message: '至少选择一项' }]}
        >
          <Select mode="multiple" virtual={false} options={problemNodeOptions} />
        </Form.Item>
        {mode === 'HUMAN'
          ? <Form.Item
            name={['admission', 'decision']}
            label="入库决定"
            rules={[{ required: true, message: '请选择入库决定' }]}
          >
            <Radio.Group options={[{ label: '入库', value: 'ADMIT' }, { label: '不入库', value: 'NOT_ADMIT' }]} />
          </Form.Item>
          : <Form.Item
            name={['admission', 'override']}
            label="自动准入复核"
            rules={[{ required: true, message: '请选择自动准入复核决定' }]}
          >
            <Radio.Group options={[
              { label: '保持 Agent 决定', value: 'KEEP' },
              { label: '改为入库', value: 'OVERRIDE_TO_ADMIT' },
              { label: '改为不入库', value: 'OVERRIDE_TO_NOT_ADMIT' },
            ]} />
          </Form.Item>}
        <Form.Item name={['admission', 'reason']} label="准入理由（选填）" initialValue="">
          <Input.TextArea rows={2} />
        </Form.Item>
        <Form.Item name="overall_comment" label="总体意见（选填）" initialValue="">
          <Input.TextArea rows={3} />
        </Form.Item>
      </Card>

      <div className="sticky-submit">
        <Space>
          <Typography.Text type="secondary">提交时会校验所有结构化字段，并标出遗漏项</Typography.Text>
          <Button
            aria-label="提交评价"
            type="primary"
            htmlType="submit"
            icon={<SendOutlined />}
            loading={submit.isPending}
          >提交评价</Button>
        </Space>
      </div>
    </Form>
  </div>
}
