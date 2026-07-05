import { describe, expect, it, vi } from 'vitest'
import { renderHook, waitFor } from '@testing-library/react'
import { useCalendarStatus } from './useCalendarStatus.ts'
import { fetchCalendarStatus } from '../api/calendar.ts'
import { ApiException } from '../api/client.ts'

vi.mock('../api/calendar.ts', () => ({
  fetchCalendarStatus: vi.fn(),
}))

describe('useCalendarStatus', () => {
  it('maps a 401 to disconnected', async () => {
    vi.mocked(fetchCalendarStatus).mockRejectedValue(new ApiException(401, 'Not authenticated'))

    const { result } = renderHook(() => useCalendarStatus())

    await waitFor(() => expect(result.current.state.status).toBe('disconnected'))
  })

  it('surfaces an error state instead of disconnected on a 500', async () => {
    vi.mocked(fetchCalendarStatus).mockRejectedValue(new ApiException(500, 'Server error'))

    const { result } = renderHook(() => useCalendarStatus())

    await waitFor(() => expect(result.current.state.status).toBe('error'))
  })

  it('surfaces an error state on a network failure', async () => {
    vi.mocked(fetchCalendarStatus).mockRejectedValue(new TypeError('Failed to fetch'))

    const { result } = renderHook(() => useCalendarStatus())

    await waitFor(() => expect(result.current.state.status).toBe('error'))
  })
})
