import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { CustomerPage } from './CustomerPage.tsx'
import { AuthContext } from '../features/auth/authContext.ts'
import { fetchUpcomingAppointments } from '../api/scheduling.ts'
import { FakeEventSource } from '../test/fakeEventSource.ts'

vi.mock('../api/scheduling.ts', () => ({
  fetchUpcomingAppointments: vi.fn(),
  createServiceCall: vi.fn(),
  createAppointment: vi.fn(),
  rescheduleAppointment: vi.fn(),
  cancelAppointment: vi.fn(),
  addAppointmentDetails: vi.fn(),
}))

const APPT = {
  id: 'a1', service_call_id: 's1', technician_id: 't1', customer_id: 'c1',
  start: '2099-06-01T09:00:00Z', end: '2099-06-01T11:00:00Z', status: 'SCHEDULED',
  details: null, problem: 'Broken boiler', technician_name: 'Tara', customer_name: 'Cara',
  address: '12 Main St', created_at: '2099-05-31T09:00:00Z',
}

function renderPage() {
  render(
    <MemoryRouter>
      <AuthContext.Provider value={{ auth: { status: 'loading' }, refresh: vi.fn() }}>
        <CustomerPage customerId="c1" />
      </AuthContext.Provider>
    </MemoryRouter>,
  )
}

describe('CustomerPage', () => {
  beforeEach(() => {
    FakeEventSource.reset()
    vi.stubGlobal('EventSource', FakeEventSource)
  })
  afterEach(() => vi.unstubAllGlobals())

  it('offers to open a service call when the customer has no upcoming appointment', async () => {
    vi.mocked(fetchUpcomingAppointments).mockResolvedValue({ items: [] })
    renderPage()
    expect(await screen.findByRole('heading', { name: /open a service call/i })).toBeInTheDocument()
  })

  it('hides the open-service-call form while an appointment is booked', async () => {
    vi.mocked(fetchUpcomingAppointments).mockResolvedValue({ items: [APPT] })
    renderPage()
    expect(await screen.findByText('Broken boiler')).toBeInTheDocument()
    expect(screen.queryByRole('heading', { name: /open a service call/i })).toBeNull()
  })

  it('exposes the customer id as a tooltip on the dashboard heading', async () => {
    vi.mocked(fetchUpcomingAppointments).mockResolvedValue({ items: [] })
    renderPage()
    const heading = await screen.findByRole('heading', { name: /customer dashboard/i })
    expect(heading).toHaveAttribute('title', 'c1')
  })
})
