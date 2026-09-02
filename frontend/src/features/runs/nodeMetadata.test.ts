import { humanizeNodeError } from './nodeMetadata'

describe('humanizeNodeError', () => {
  it('turns a non-N12 template validation failure into an actionable Chinese cause', () => {
    expect(humanizeNodeError(
      'N10 template must contain reusable slots and meaningful fixed structure',
      'NODE_OUTPUT_VALIDATION_FAILED',
    )).toBe('提取的模板缺少可复用槽位或有意义的固定结构。')
  })

  it('explains provider timeouts without exposing only an English exception', () => {
    expect(humanizeNodeError('request timed out', 'NODE_TIMEOUT')).toBe(
      '节点调用外部服务超时，本次没有得到完整结果。',
    )
  })
})
