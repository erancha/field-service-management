import { afterEach, describe, expect, it, vi } from 'vitest'
import { apiGet, apiPatch, apiUpload, ApiException } from './client.ts'
import { updateProfile } from './auth.ts'

afterEach(() => vi.unstubAllGlobals())

/**
 * Stand-in for XMLHttpRequest that records what was sent and lets a test drive the upload
 * progress and completion callbacks by hand, so no real request or timing is involved.
 */
class FakeXhr {
  static last: FakeXhr
  upload = { onprogress: null as ((e: ProgressEvent) => void) | null }
  onload: (() => void) | null = null
  onerror: (() => void) | null = null
  status = 0
  responseText = ''
  withCredentials = false
  method = ''
  url = ''
  sent: unknown = null

  constructor() {
    FakeXhr.last = this
  }

  open(method: string, url: string) {
    this.method = method
    this.url = url
  }

  send(body: unknown) {
    this.sent = body
  }

  emitProgress(loaded: number, total: number) {
    this.upload.onprogress?.({ lengthComputable: true, loaded, total } as ProgressEvent)
  }

  finish(status: number, body: string) {
    this.status = status
    this.responseText = body
    this.onload?.()
  }
}

describe('handleResponse on an empty body', () => {
  it('throws instead of fabricating {} for a typed call', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response('', { status: 200 })))

    await expect(apiGet('/auth/me')).rejects.toBeInstanceOf(ApiException)
  })
})

describe('apiPatch', () => {
  it('sends a PATCH with a JSON body', async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValue(new Response(JSON.stringify({ ok: true }), { status: 200 }))
    vi.stubGlobal('fetch', fetchMock)

    await apiPatch('/auth/me', { address: '12 Main St' })

    const [path, options] = fetchMock.mock.calls[0]
    expect(path).toBe('/auth/me')
    expect(options.method).toBe('PATCH')
    expect(JSON.parse(options.body as string)).toEqual({ address: '12 Main St' })
  })
})

describe('apiUpload', () => {
  it('reports the transferred fraction and resolves with the parsed body', async () => {
    vi.stubGlobal('XMLHttpRequest', FakeXhr)
    const fractions: number[] = []
    const form = new FormData()

    const pending = apiUpload<{ id: string }>('/api/kb/documents', form, (f) => fractions.push(f))
    const xhr = FakeXhr.last
    xhr.emitProgress(25, 100)
    xhr.emitProgress(100, 100)
    xhr.finish(201, JSON.stringify({ id: 'd1' }))

    expect(await pending).toEqual({ id: 'd1' })
    expect(fractions).toEqual([0.25, 1])
    expect(xhr.method).toBe('POST')
    expect(xhr.url).toBe('/api/kb/documents')
    expect(xhr.withCredentials).toBe(true)
    expect(xhr.sent).toBe(form)
  })

  it('rejects with the server detail on an error status', async () => {
    vi.stubGlobal('XMLHttpRequest', FakeXhr)

    const pending = apiUpload('/api/kb/documents', new FormData())
    FakeXhr.last.finish(413, JSON.stringify({ detail: 'Document exceeds the 20 MB limit' }))

    await expect(pending).rejects.toMatchObject({
      status: 413,
      detail: 'Document exceeds the 20 MB limit',
    })
  })

  it('rejects when the transport fails before any response', async () => {
    vi.stubGlobal('XMLHttpRequest', FakeXhr)

    const pending = apiUpload('/api/kb/documents', new FormData())
    FakeXhr.last.onerror?.()

    await expect(pending).rejects.toBeInstanceOf(ApiException)
  })
})

describe('updateProfile', () => {
  it('PATCHes /auth/me and returns the updated user', async () => {
    const updated = {
      user_id: 'u1',
      email: 'a@b.example',
      role: 'CUSTOMER',
      role_status: 'APPROVED',
      name: 'Alice',
      display_name: 'Dana',
      address: null,
      phone: null,
    }
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(new Response(JSON.stringify(updated), { status: 200 })),
    )

    const result = await updateProfile({ display_name: 'Dana' })

    expect(result.display_name).toBe('Dana')
  })
})
