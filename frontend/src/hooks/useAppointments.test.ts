import { describe, expect, it, vi } from 'vitest'
import { act, renderHook } from '@testing-library/react'
import { useAppointments } from './useAppointments.ts'
import { createAppointment } from '../api/scheduling.ts'
import type { Appointment } from '../api/types.ts'

vi.mock('../api/scheduling.ts', () => ({
  createAppointment: vi.fn(),
  rescheduleAppointment: vi.fn(),
  cancelAppointment: vi.fn(),
  addAppointmentDetails: vi.fn(),
}))

const request = {
  service_call_id: 'sc-1',
  technician_id: 'tech-1',
  start: '2026-07-07T09:00:00Z',
  end: '2026-07-07T10:00:00Z',
}

const appointment: Appointment = {
  id: 'appt-1',
  service_call_id: 'sc-1',
  technician_id: 'tech-1',
  customer_id: 'cust-1',
  start: '2026-07-07T09:00:00Z',
  end: '2026-07-07T10:00:00Z',
  status: 'SCHEDULED',
}

describe('useAppointments.book', () => {
  it('resolves to the created appointment on success', async () => {
    vi.mocked(createAppointment).mockResolvedValue(appointment)

    const { result } = renderHook(() => useAppointments())

    let returned: Appointment | null = null
    await act(async () => {
      returned = await result.current.book(request)
    })

    expect(returned).toEqual(appointment)
  })

  it('resolves to null and sets error on failure', async () => {
    vi.mocked(createAppointment).mockRejectedValue(new Error('Slot already taken'))

    const { result } = renderHook(() => useAppointments())

    let returned: Appointment | null = appointment
    await act(async () => {
      returned = await result.current.book(request)
    })

    expect(returned).toBeNull()
    expect(result.current.error).toBe('Slot already taken')
  })
})
