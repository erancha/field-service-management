import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { renderHook, act, waitFor } from '@testing-library/react'
import { useUpcomingAppointments } from './useUpcomingAppointments.ts'
import { fetchUpcomingAppointments } from '../api/scheduling.ts'
import { FakeEventSource } from '../test/fakeEventSource.ts'

vi.mock('../api/scheduling.ts', () => ({ fetchUpcomingAppointments: vi.fn() }))

const ITEM = {
  id: 'a1', service_call_id: 's1', technician_id: 't1', customer_id: 'c1',
  start: '2099-06-01T09:00:00Z', end: '2099-06-01T11:00:00Z', status: 'SCHEDULED',
  details: null, problem: 'Fix boiler', technician_name: 'Tara', customer_name: 'Cara', address: '12 Main St',
}

describe('useUpcomingAppointments', () => {
  beforeEach(() => {
    FakeEventSource.reset()
    vi.stubGlobal('EventSource', FakeEventSource)
    vi.mocked(fetchUpcomingAppointments).mockClear().mockResolvedValue({ items: [ITEM] })
  })
  afterEach(() => vi.unstubAllGlobals())

  it('fetches on mount with the given limit', async () => {
    const { result } = renderHook(() => useUpcomingAppointments(5))
    await waitFor(() => expect(result.current.items).toEqual([ITEM]))
    expect(fetchUpcomingAppointments).toHaveBeenCalledWith({ limit: 5 })
  })

  it('refetches on an appointment.changed event', async () => {
    renderHook(() => useUpcomingAppointments(5))
    await waitFor(() => expect(fetchUpcomingAppointments).toHaveBeenCalledTimes(1))
    await act(async () => { FakeEventSource.last().emit('appointment.changed', { appointment_id: 'a1' }) })
    await waitFor(() => expect(fetchUpcomingAppointments).toHaveBeenCalledTimes(2))
  })

  it('refetches on reconnect but not on the first open', async () => {
    renderHook(() => useUpcomingAppointments(5))
    await waitFor(() => expect(fetchUpcomingAppointments).toHaveBeenCalledTimes(1))
    await act(async () => { FakeEventSource.last().open() })  // first open — no extra fetch
    await act(async () => { FakeEventSource.last().open() })  // reconnect — refetch
    await waitFor(() => expect(fetchUpcomingAppointments).toHaveBeenCalledTimes(2))
  })
})
