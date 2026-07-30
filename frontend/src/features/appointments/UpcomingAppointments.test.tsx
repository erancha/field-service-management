import { describe, expect, it, vi } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { UpcomingAppointments } from './UpcomingAppointments.tsx'
import { cancelAppointment } from '../../api/scheduling.ts'
import type { UpcomingAppointment } from '../../api/types.ts'

vi.mock('../../api/scheduling.ts', () => ({
  rescheduleAppointment: vi.fn(),
  cancelAppointment: vi.fn(),
  addAppointmentDetails: vi.fn(),
  createAppointment: vi.fn(),
}))

const ITEM: UpcomingAppointment = {
  id: 'a1', service_call_id: 's1', technician_id: 't1', customer_id: 'c1',
  start: '2099-06-01T09:00:00Z', end: '2099-06-01T11:00:00Z', status: 'SCHEDULED',
  details: null, problem: 'Fix boiler', technician_name: 'Tara', customer_name: 'Cara', address: '12 Main St',
  created_at: '2020-01-01T00:00:00Z', photos: [],
}

function renderList(overrides: Partial<React.ComponentProps<typeof UpcomingAppointments>> = {}) {
  render(
    <UpcomingAppointments
      items={[ITEM]}
      loading={false}
      error={null}
      refetch={vi.fn().mockResolvedValue(undefined)}
      showTechnicianName={false}
      showReschedule={false}
      showCancel={false}
      {...overrides}
    />,
  )
}

describe('UpcomingAppointments', () => {
  it('renders a row with the problem and customer name', () => {
    renderList()
    expect(screen.getByText('Fix boiler')).toBeInTheDocument()
    expect(screen.getByText(/Cara/)).toBeInTheDocument()
  })

  it('hides the technician name when showTechnicianName is false', () => {
    renderList()
    expect(screen.queryByText(/Tara/)).not.toBeInTheDocument()
  })

  it('shows the technician name on the back-office/customer view', () => {
    renderList({ showTechnicianName: true })
    expect(screen.getByText(/Tara/)).toBeInTheDocument()
  })

  it('opens the detail card and offers Reschedule only when allowed', async () => {
    renderList({ showTechnicianName: true, showReschedule: true })
    await userEvent.click(screen.getByRole('button', { name: /expand appointment/i }))
    expect(screen.getByRole('button', { name: /^reschedule$/i })).toBeInTheDocument()
  })

  it('lets the customer cancel an opened appointment and refreshes the list', async () => {
    const refetch = vi.fn().mockResolvedValue(undefined)
    vi.mocked(cancelAppointment).mockResolvedValue({
      id: 'a1', service_call_id: 's1', technician_id: 't1', customer_id: 'c1',
      start: ITEM.start, end: ITEM.end, status: 'CANCELLED',
    })
    renderList({ showTechnicianName: true, showReschedule: true, showCancel: true, refetch })

    await userEvent.click(screen.getByRole('button', { name: /expand appointment/i }))
    await userEvent.click(screen.getByRole('button', { name: /^cancel appointment$/i }))
    await userEvent.click(screen.getByRole('button', { name: /yes, cancel appointment/i }))

    expect(cancelAppointment).toHaveBeenCalledWith('a1')
    await waitFor(() => expect(refetch).toHaveBeenCalled())
  })

  it('lets the technician cancel without reschedule when showCancel is set alone', async () => {
    const refetch = vi.fn().mockResolvedValue(undefined)
    vi.mocked(cancelAppointment).mockResolvedValue({
      id: 'a1', service_call_id: 's1', technician_id: 't1', customer_id: 'c1',
      start: ITEM.start, end: ITEM.end, status: 'CANCELLED',
    })
    renderList({ showReschedule: false, showCancel: true, refetch })

    await userEvent.click(screen.getByRole('button', { name: /expand appointment/i }))
    expect(screen.queryByRole('button', { name: /^reschedule$/i })).toBeNull()
    await userEvent.click(screen.getByRole('button', { name: /^cancel appointment$/i }))
    await userEvent.click(screen.getByRole('button', { name: /yes, cancel appointment/i }))

    expect(cancelAppointment).toHaveBeenCalledWith('a1')
    await waitFor(() => expect(refetch).toHaveBeenCalled())
  })

  it('does not offer cancel on the read-only (admin) view', async () => {
    renderList({ showTechnicianName: true, showReschedule: false, showCancel: false })
    await userEvent.click(screen.getByRole('button', { name: /expand appointment/i }))
    expect(screen.queryByRole('button', { name: /cancel appointment/i })).toBeNull()
  })

  it('highlights appointments scheduled within the last 24 hours', () => {
    const recent = { ...ITEM, id: 'a2', problem: 'Just booked', created_at: new Date(Date.now() - 3_600_000).toISOString() }
    renderList({ items: [recent, ITEM], showTechnicianName: true, showReschedule: true })
    expect(screen.getByText('Just booked').closest('li')).toHaveClass('upcoming__item--recent')
    expect(screen.getByText('Fix boiler').closest('li')).not.toHaveClass('upcoming__item--recent')
  })

  it('shows an empty state when there are none', () => {
    renderList({ items: [] })
    expect(screen.getByText(/no upcoming appointments/i)).toBeInTheDocument()
  })
})
