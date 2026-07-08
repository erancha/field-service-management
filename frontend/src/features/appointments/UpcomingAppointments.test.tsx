import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { UpcomingAppointments } from './UpcomingAppointments.tsx'
import { fetchUpcomingAppointments } from '../../api/scheduling.ts'
import { FakeEventSource } from '../../test/fakeEventSource.ts'

vi.mock('../../api/scheduling.ts', () => ({
  fetchUpcomingAppointments: vi.fn(),
  rescheduleAppointment: vi.fn(),
  cancelAppointment: vi.fn(),
  addAppointmentDetails: vi.fn(),
  createAppointment: vi.fn(),
}))

const ITEM = {
  id: 'a1', service_call_id: 's1', technician_id: 't1', customer_id: 'c1',
  start: '2099-06-01T09:00:00Z', end: '2099-06-01T11:00:00Z', status: 'SCHEDULED',
  details: null, problem: 'Fix boiler', technician_name: 'Tara', customer_name: 'Cara', address: '12 Main St',
}

describe('UpcomingAppointments', () => {
  beforeEach(() => {
    FakeEventSource.reset()
    vi.stubGlobal('EventSource', FakeEventSource)
    vi.mocked(fetchUpcomingAppointments).mockResolvedValue({ items: [ITEM] })
  })
  afterEach(() => vi.unstubAllGlobals())

  it('renders a row with the problem and customer name', async () => {
    render(<UpcomingAppointments limit={5} showTechnicianName={false} showReschedule={false} />)
    expect(await screen.findByText('Fix boiler')).toBeInTheDocument()
    expect(screen.getByText(/Cara/)).toBeInTheDocument()
  })

  it('hides the technician name when showTechnicianName is false', async () => {
    render(<UpcomingAppointments limit={5} showTechnicianName={false} showReschedule={false} />)
    await screen.findByText('Fix boiler')
    expect(screen.queryByText(/Tara/)).not.toBeInTheDocument()
  })

  it('shows the technician name on the back-office/customer view', async () => {
    render(<UpcomingAppointments limit={10} showTechnicianName showReschedule={false} />)
    expect(await screen.findByText(/Tara/)).toBeInTheDocument()
  })

  it('opens the detail card and offers Reschedule only when allowed', async () => {
    render(<UpcomingAppointments limit={3} showTechnicianName showReschedule />)
    await userEvent.click(await screen.findByRole('button', { name: /open/i }))
    expect(screen.getByRole('button', { name: /^reschedule$/i })).toBeInTheDocument()
  })

  it('shows an empty state when there are none', async () => {
    vi.mocked(fetchUpcomingAppointments).mockResolvedValue({ items: [] })
    render(<UpcomingAppointments limit={5} showTechnicianName={false} showReschedule={false} />)
    expect(await screen.findByText(/no upcoming appointments/i)).toBeInTheDocument()
  })
})
