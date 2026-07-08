import { describe, expect, it, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { TechnicianPage } from './TechnicianPage.tsx'
import { AuthContext } from '../features/auth/authContext.ts'
import { fetchCalendarStatus, disconnectCalendar } from '../api/calendar.ts'
import { fetchUpcomingAppointments } from '../api/scheduling.ts'
import { FakeEventSource } from '../test/fakeEventSource.ts'

vi.mock('../api/calendar.ts', () => ({
  fetchCalendarStatus: vi.fn(),
  disconnectCalendar: vi.fn(),
}))
vi.mock('../api/scheduling.ts', () => ({ fetchUpcomingAppointments: vi.fn() }))

const TECHNICIAN_ID = 'a7371688-9873-40e1-b1fe-197b3f5d211d'

function renderPage() {
  render(
    <MemoryRouter>
      <AuthContext.Provider value={{ auth: { status: 'loading' }, refresh: vi.fn() }}>
        <TechnicianPage technicianId={TECHNICIAN_ID} />
      </AuthContext.Provider>
    </MemoryRouter>,
  )
}

describe('TechnicianPage', () => {
  beforeEach(() => {
    vi.mocked(fetchCalendarStatus).mockReset()
    vi.mocked(disconnectCalendar).mockReset()
    FakeEventSource.reset()
    vi.stubGlobal('EventSource', FakeEventSource)
    vi.mocked(fetchUpcomingAppointments).mockResolvedValue({ items: [] })
  })
  afterEach(() => vi.unstubAllGlobals())

  it('links the connected indication to Google Calendar and drops the My Appointments section', async () => {
    vi.mocked(fetchCalendarStatus).mockResolvedValue({ connected: true, fsm_calendar_id: 'cal-1' })
    renderPage()

    const calendarLink = await screen.findByRole('link', { name: /google calendar connected/i })
    expect(calendarLink).toHaveAttribute('href', 'https://calendar.google.com/calendar/')
    expect(calendarLink).toHaveAttribute('target', '_blank')
    expect(screen.queryByText(/google calendar integration/i)).toBeNull()
    expect(screen.queryByRole('heading', { name: /my appointments/i })).toBeNull()
    await waitFor(() => expect(FakeEventSource.instances.length).toBeGreaterThan(0))
  })

  it('exposes the technician id as a tooltip on the dashboard heading', async () => {
    vi.mocked(fetchCalendarStatus).mockResolvedValue({ connected: false, fsm_calendar_id: null })
    renderPage()

    const heading = await screen.findByRole('heading', { name: /technician dashboard/i })
    expect(heading).toHaveAttribute('title', TECHNICIAN_ID)
  })

  it('lets a connected technician disconnect and returns to the connect card', async () => {
    vi.mocked(fetchCalendarStatus)
      .mockResolvedValueOnce({ connected: true, fsm_calendar_id: 'cal-1' })
      .mockResolvedValueOnce({ connected: false, fsm_calendar_id: null })
    vi.mocked(disconnectCalendar).mockResolvedValue(undefined)
    renderPage()

    await userEvent.click(await screen.findByRole('button', { name: /disconnect/i }))
    await userEvent.click(screen.getByRole('button', { name: /confirm/i }))

    expect(disconnectCalendar).toHaveBeenCalledOnce()
    expect(
      await screen.findByRole('link', { name: /connect google calendar/i }),
    ).toBeInTheDocument()
  })

  it('shows the integration card with the connect link while disconnected, with no inline indication', async () => {
    vi.mocked(fetchCalendarStatus).mockResolvedValue({ connected: false, fsm_calendar_id: null })
    renderPage()

    expect(
      await screen.findByRole('link', { name: /connect google calendar/i }),
    ).toBeInTheDocument()
    expect(screen.getByText(/google calendar integration/i)).toBeInTheDocument()
    expect(screen.queryByText(/google calendar connected/i)).toBeNull()
  })
})
