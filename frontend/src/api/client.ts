import type { ApiError } from './types.ts'

export class ApiException extends Error {
  readonly status: number
  readonly detail: string

  constructor(status: number, detail: string) {
    super(detail)
    this.name = 'ApiException'
    this.status = status
    this.detail = detail
  }
}

async function handleResponse<T>(res: Response): Promise<T> {
  if (res.ok) {
    const text = await res.text()
    if (!text) {
      throw new ApiException(res.status, `HTTP ${res.status} with an empty response body`)
    }
    return JSON.parse(text) as T
  }

  let detail = `HTTP ${res.status}`
  try {
    const body = (await res.json()) as ApiError
    if (body.detail) detail = body.detail
  } catch {
    // body wasn't JSON — keep the default
  }
  throw new ApiException(res.status, detail)
}

export async function apiFetch<T>(
  path: string,
  options?: RequestInit,
): Promise<T> {
  const res = await fetch(path, {
    headers: { 'Content-Type': 'application/json', ...options?.headers },
    credentials: 'include',
    ...options,
  })
  return handleResponse<T>(res)
}

export async function apiPost<T>(path: string, body: unknown): Promise<T> {
  return apiFetch<T>(path, {
    method: 'POST',
    body: JSON.stringify(body),
  })
}

export async function apiPatch<T>(path: string, body: unknown): Promise<T> {
  return apiFetch<T>(path, {
    method: 'PATCH',
    body: JSON.stringify(body),
  })
}

export async function apiGet<T>(path: string, params?: Record<string, string>): Promise<T> {
  const url = params
    ? `${path}?${new URLSearchParams(params).toString()}`
    : path
  return apiFetch<T>(url, { method: 'GET' })
}

export async function apiDelete<T>(path: string): Promise<T> {
  return apiFetch<T>(path, { method: 'DELETE' })
}

export async function apiUpload<T>(path: string, form: FormData): Promise<T> {
  const res = await fetch(path, {
    method: 'POST',
    body: form,
    credentials: 'include',
  })
  return handleResponse<T>(res)
}
