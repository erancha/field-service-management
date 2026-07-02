import { beforeEach, describe, expect, it, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { AppointmentCard } from './AppointmentCard.tsx'
import { fetchAvailability } from '../api/scheduling.ts'
import type { Appointment } from '../api/types.ts'

vi.mock('../api/scheduling.ts', () => ({
  fetchAvailability: vi.fn(),
}))

const SLOT = { start: '2026-07-06T09:00:00+03:00', end: '2026-07-06T10:00:00+03:00' }

function makeAppointment(overrides: Partial<Appointment> = {}): Appointment {
  return {
    id: 'a1b2c3d4-0000-0000-0000-000000000000',
    service_call_id: 'sc-1',
    technician_id: 'tech-1',
    customer_id: 'cust-1',
    start: '2026-07-05T09:00:00+03:00',
    end: '2026-07-05T10:00:00+03:00',
    status: 'booked',
    ...overrides,
  }
}

beforeEach(() => {
  vi.mocked(fetchAvailability).mockReset()
  vi.mocked(fetchAvailability).mockResolvedValue({ slots: [SLOT] })
})

describe('AppointmentCard reschedule', () => {
  it('offers available slots instead of free-form time inputs', async () => {
    const onReschedule = vi.fn()
    const { container } = render(
      <AppointmentCard appointment={makeAppointment()} onReschedule={onReschedule} />,
    )

    await userEvent.click(screen.getByRole('button', { name: /^reschedule$/i }))

    await screen.findByRole('button', { name: /–/ })
    expect(container.querySelector('input[type="datetime-local"]')).toBeNull()
    expect(fetchAvailability).toHaveBeenCalledWith(
      expect.objectContaining({ technician_id: 'tech-1' }),
    )
  })

  it('reschedules to the selected slot', async () => {
    const onReschedule = vi.fn()
    const appointment = makeAppointment()
    render(<AppointmentCard appointment={appointment} onReschedule={onReschedule} />)

    await userEvent.click(screen.getByRole('button', { name: /^reschedule$/i }))
    await userEvent.click(await screen.findByRole('button', { name: /–/ }))
    await userEvent.click(screen.getByRole('button', { name: /confirm/i }))

    expect(onReschedule).toHaveBeenCalledWith(appointment.id, SLOT.start, SLOT.end)
  })
})

describe('AppointmentCard cancelled state', () => {
  it('offers no actions on a cancelled appointment', () => {
    render(
      <AppointmentCard
        appointment={makeAppointment({ status: 'cancelled' })}
        onReschedule={vi.fn()}
        onCancel={vi.fn()}
        onAddDetails={vi.fn()}
      />,
    )

    expect(screen.queryByRole('button')).toBeNull()
  })
})
