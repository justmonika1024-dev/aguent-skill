import { api } from './client'

describe('api client', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('returns parsed JSON for successful responses', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(JSON.stringify({ ok: true }), {
      status: 200,
      headers: { 'content-type': 'application/json' },
    })))
    await expect(api.get<{ ok: boolean }>('/health')).resolves.toEqual({ ok: true })
  })

  it('turns the standard backend error into ApiError', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(JSON.stringify({
      error: { code: 'ACTIVE_RUN_EXISTS', message: '已有任务', request_id: 'req-1' },
    }), { status: 409, headers: { 'content-type': 'application/json' } })))
    await expect(api.post('/runs', {})).rejects.toEqual(expect.objectContaining({
      code: 'ACTIVE_RUN_EXISTS',
      message: '已有任务',
      status: 409,
    }))
  })

  it('accepts a successful empty response', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(null, { status: 204 })))
    await expect(api.post('/noop')).resolves.toBeUndefined()
  })
})
