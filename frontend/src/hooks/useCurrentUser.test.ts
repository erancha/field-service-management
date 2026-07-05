import { describe, expect, it, vi } from 'vitest'
import { renderHook, waitFor } from '@testing-library/react'
import { useCurrentUser } from './useCurrentUser.ts'
import { fetchCurrentUser } from '../api/auth.ts'

vi.mock('../api/auth.ts', () => ({
  fetchCurrentUser: vi.fn(),
}))

describe('useCurrentUser', () => {
  it('resolves to unauthenticated when signed out', async () => {
    vi.mocked(fetchCurrentUser).mockResolvedValue(null)

    const { result } = renderHook(() => useCurrentUser())

    await waitFor(() => expect(result.current.auth.status).toBe('unauthenticated'))
  })

  it('surfaces an error state instead of unauthenticated on a real failure', async () => {
    vi.mocked(fetchCurrentUser).mockRejectedValue(new Error('boom'))

    const { result } = renderHook(() => useCurrentUser())

    await waitFor(() => expect(result.current.auth.status).toBe('error'))
  })
})
