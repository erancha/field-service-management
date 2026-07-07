import { afterEach, describe, expect, it, vi } from 'vitest'
import { apiGet, apiPatch, ApiException } from './client.ts'
import { updateProfile } from './auth.ts'

afterEach(() => vi.unstubAllGlobals())

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
