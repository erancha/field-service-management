import { afterEach, describe, expect, it, vi } from 'vitest'
import { fetchCurrentUser } from './auth.ts'

afterEach(() => vi.unstubAllGlobals())

describe('fetchCurrentUser', () => {
  it('returns null on a 401', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(new Response(JSON.stringify({ detail: 'nope' }), { status: 401 })),
    )

    await expect(fetchCurrentUser()).resolves.toBeNull()
  })

  it('propagates a 500', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(new Response(JSON.stringify({ detail: 'boom' }), { status: 500 })),
    )

    await expect(fetchCurrentUser()).rejects.toMatchObject({ status: 500 })
  })

  it('propagates a network failure', async () => {
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new TypeError('Failed to fetch')))

    await expect(fetchCurrentUser()).rejects.toThrow('Failed to fetch')
  })
})
