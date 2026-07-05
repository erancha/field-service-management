import { describe, expect, it, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { AuthContext } from '../auth/authContext.ts'
import type { Appointment, CurrentUser, ServiceCall } from '../../api/types.ts'
import { createAppointment, fetchPooledAvailability } from '../../api/scheduling.ts'
import { BookFlow } from './BookFlow.tsx'

vi.mock('../../api/scheduling.ts', () => ({
  fetchPooledAvailability: vi.fn(),
  createAppointment: vi.fn(),
  rescheduleAppointment: vi.fn(),
  cancelAppointment: vi.fn(),
  addAppointmentDetails: vi.fn(),
}))

const serviceCall: ServiceCall = {
  id: 'sc-1',
  customer_id: 'cust-1',
  description: 'Broken boiler',
  status: 'OPEN',
  created_at: '2026-07-06T08:00:00Z',
}

const slot = {
  technician_id: 'tech-1',
  technician_name: 'Dana',
  start: '2026-07-07T09:00:00Z',
  end: '2026-07-07T10:00:00Z',
}

const appointment: Appointment = {
  id: 'appt-1',
  service_call_id: serviceCall.id,
  technician_id: slot.technician_id,
  customer_id: serviceCall.customer_id,
  start: slot.start,
  end: slot.end,
  status: 'SCHEDULED',
}

function renderBookFlow() {
  const user: CurrentUser = {
    user_id: 'cust-1',
    email: 'c@example.com',
    role: 'CUSTOMER',
    role_status: 'APPROVED',
    name: 'Customer',
    display_name: null,
    address: '12 Main St',
    phone: '054-1234567',
  }
  render(
    <AuthContext.Provider value={{ auth: { status: 'authenticated', user }, refresh: vi.fn() }}>
      <MemoryRouter>
        <BookFlow serviceCall={serviceCall} />
      </MemoryRouter>
    </AuthContext.Provider>,
  )
}

describe('BookFlow', () => {
  it('shows the confirmation screen when booking succeeds', async () => {
    vi.mocked(fetchPooledAvailability).mockResolvedValue({ slots: [slot] })
    vi.mocked(createAppointment).mockResolvedValue(appointment)

    renderBookFlow()

    await userEvent.click(await screen.findByRole('button', { name: /dana/i }))
    await userEvent.click(screen.getByRole('button', { name: /book selected slot/i }))

    expect(await screen.findByText('Appointment Booked')).toBeInTheDocument()
  })

  it('stays on the slot screen with an error when booking fails', async () => {
    vi.mocked(fetchPooledAvailability).mockResolvedValue({ slots: [slot] })
    vi.mocked(createAppointment).mockRejectedValue(new Error('Slot already taken'))

    renderBookFlow()

    await userEvent.click(await screen.findByRole('button', { name: /dana/i }))
    await userEvent.click(screen.getByRole('button', { name: /book selected slot/i }))

    expect(await screen.findByText('Slot already taken')).toBeInTheDocument()
    expect(screen.queryByText('Appointment Booked')).toBeNull()
  })

  it('shows the confirmation screen when a retry succeeds after a failed attempt', async () => {
    vi.mocked(fetchPooledAvailability).mockResolvedValue({ slots: [slot] })
    vi.mocked(createAppointment)
      .mockRejectedValueOnce(new Error('Slot already taken'))
      .mockResolvedValueOnce(appointment)

    renderBookFlow()

    await userEvent.click(await screen.findByRole('button', { name: /dana/i }))
    const bookButton = screen.getByRole('button', { name: /book selected slot/i })
    await userEvent.click(bookButton)
    expect(await screen.findByText('Slot already taken')).toBeInTheDocument()

    await userEvent.click(bookButton)

    expect(await screen.findByText('Appointment Booked')).toBeInTheDocument()
  })
})
