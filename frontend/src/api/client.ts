const API_ROOT = '/api/v1'

interface BackendError {
  error?: {
    code?: string
    message?: string
    request_id?: string
    details?: unknown
  }
  detail?: unknown
}

function detailObject(detail: unknown): { code?: string; message?: string; details?: unknown } {
  return detail && typeof detail === 'object' ? detail as { code?: string; message?: string; details?: unknown } : {}
}

export class ApiError extends Error {
  constructor(
    message: string,
    public readonly code: string,
    public readonly status: number,
    public readonly requestId?: string,
    public readonly details?: unknown,
  ) {
    super(message)
    this.name = 'ApiError'
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_ROOT}${path}`, {
    ...init,
    headers: {
      Accept: 'application/json',
      ...(init?.body ? { 'Content-Type': 'application/json' } : {}),
      ...init?.headers,
    },
  })
  if (!response.ok) {
    let payload: BackendError = {}
    try {
      payload = await response.json() as BackendError
    } catch {
      payload = {}
    }
    const detail = detailObject(payload.detail)
    throw new ApiError(
      payload.error?.message ?? detail.message ?? (typeof payload.detail === 'string' ? payload.detail : `请求失败（HTTP ${response.status}）`),
      payload.error?.code ?? detail.code ?? `HTTP_${response.status}`,
      response.status,
      payload.error?.request_id,
      payload.error?.details ?? detail.details ?? payload.detail,
    )
  }
  if (response.status === 204) return undefined as T
  const text = await response.text()
  return (text ? JSON.parse(text) : undefined) as T
}

export const api = {
  get: <T>(path: string, signal?: AbortSignal) => request<T>(path, { signal }),
  post: <T = void>(path: string, body?: unknown) => request<T>(path, {
    method: 'POST',
    body: body === undefined ? undefined : JSON.stringify(body),
  }),
  patch: <T>(path: string, body: unknown) => request<T>(path, {
    method: 'PATCH',
    body: JSON.stringify(body),
  }),
}
