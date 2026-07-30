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

function parseResponseBody<T>(status: number, ok: boolean, body: string): T {
  if (ok) {
    if (!body) {
      throw new ApiException(status, `HTTP ${status} with an empty response body`)
    }
    return JSON.parse(body) as T
  }

  let detail = `HTTP ${status}`
  try {
    const parsed = JSON.parse(body) as ApiError
    if (parsed.detail) detail = parsed.detail
  } catch {
    // body wasn't JSON — keep the default
  }
  throw new ApiException(status, detail)
}

async function handleResponse<T>(res: Response): Promise<T> {
  return parseResponseBody<T>(res.status, res.ok, await res.text())
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

/**
 * POSTs a multipart body, optionally reporting how much of it has reached the server.
 *
 * Uses XMLHttpRequest rather than fetch because fetch exposes no request-body progress, and a
 * multi-megabyte upload otherwise gives the operator no signal for its first several seconds.
 * onProgress receives a 0..1 fraction, and only while the length is known; reaching 1 means the
 * bytes are delivered, not that the server has finished processing them.
 */
export function apiUpload<T>(
  path: string,
  form: FormData,
  onProgress?: (fraction: number) => void,
): Promise<T> {
  return new Promise<T>((resolve, reject) => {
    const xhr = new XMLHttpRequest()
    xhr.open('POST', path)
    xhr.withCredentials = true

    if (onProgress) {
      xhr.upload.onprogress = (e) => {
        if (e.lengthComputable) onProgress(e.loaded / e.total)
      }
    }

    xhr.onload = () => {
      const ok = xhr.status >= 200 && xhr.status < 300
      try {
        resolve(parseResponseBody<T>(xhr.status, ok, xhr.responseText))
      } catch (e) {
        reject(e)
      }
    }
    // xhr.status is 0 here: the transport failed before any response line was read.
    xhr.onerror = () => reject(new ApiException(xhr.status, 'The upload could not reach the server'))

    xhr.send(form)
  })
}
