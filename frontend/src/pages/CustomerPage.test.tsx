import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { CustomerPage } from './CustomerPage.tsx'
import { AuthContext } from '../features/auth/authContext.ts'
import {
  createServiceCall,
  fetchPooledAvailability,
  fetchUpcomingAppointments,
} from '../api/scheduling.ts'
import { fetchAssistStatus, startConversation, streamAssistReply } from '../api/assist.ts'
import { ApiException } from '../api/client.ts'
import { FakeEventSource } from '../test/fakeEventSource.ts'

vi.mock('../api/scheduling.ts', () => ({
  fetchUpcomingAppointments: vi.fn(),
  fetchPooledAvailability: vi.fn(),
  createServiceCall: vi.fn(),
  createAppointment: vi.fn(),
  rescheduleAppointment: vi.fn(),
  cancelAppointment: vi.fn(),
  addAppointmentDetails: vi.fn(),
}))

vi.mock('../api/assist.ts', () => ({
  fetchAssistStatus: vi.fn(),
  startConversation: vi.fn(),
  streamAssistReply: vi.fn(),
  endConversation: vi.fn(),
  listPastConversations: vi.fn().mockResolvedValue([]),
  fetchConversation: vi.fn(),
  uploadTriagePhoto: vi.fn(),
  deleteTriagePhoto: vi.fn(),
  triagePhotoPreviewUrl: (conversationId: string, photoId: string) =>
    `/api/assist/conversations/${conversationId}/photos/${photoId}/preview`,
}))

const APPT = {
  id: 'a1', service_call_id: 's1', technician_id: 't1', customer_id: 'c1',
  start: '2099-06-01T09:00:00Z', end: '2099-06-01T11:00:00Z', status: 'SCHEDULED',
  details: null, problem: 'Broken boiler', technician_name: 'Tara', customer_name: 'Cara',
  address: '12 Main St', created_at: '2099-05-31T09:00:00Z', photos: [],
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
    vi.mocked(fetchAssistStatus).mockResolvedValue({ enabled: false })
    vi.mocked(startConversation).mockResolvedValue({
      id: 'c1', status: 'ACTIVE', service_call_id: null, messages: [], pending_photos: [],
    })
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

  it('shows the triage chat when the assistant is configured', async () => {
    vi.mocked(fetchUpcomingAppointments).mockResolvedValue({ items: [] })
    vi.mocked(fetchAssistStatus).mockResolvedValue({ enabled: true })

    renderPage()

    expect(await screen.findByRole('heading', { name: /tell us what is wrong/i }))
      .toBeInTheDocument()
    expect(screen.queryByRole('heading', { name: /open a service call/i })).not.toBeInTheDocument()
  })

  it('falls back to the classic form when the assistant is not configured', async () => {
    vi.mocked(fetchUpcomingAppointments).mockResolvedValue({ items: [] })
    vi.mocked(fetchAssistStatus).mockResolvedValue({ enabled: false })

    renderPage()

    expect(await screen.findByRole('heading', { name: /open a service call/i }))
      .toBeInTheDocument()
    expect(screen.queryByRole('heading', { name: /tell us what is wrong/i })).not.toBeInTheDocument()
  })

  it('falls back to the classic form when the status check fails', async () => {
    vi.mocked(fetchUpcomingAppointments).mockResolvedValue({ items: [] })
    vi.mocked(fetchAssistStatus).mockRejectedValue(new Error('offline'))

    renderPage()

    expect(await screen.findByRole('heading', { name: /open a service call/i }))
      .toBeInTheDocument()
  })

  it('escapes to the classic form when a triage turn fails, and still opens a service call', async () => {
    vi.mocked(fetchUpcomingAppointments).mockResolvedValue({ items: [] })
    vi.mocked(fetchAssistStatus).mockResolvedValue({ enabled: true })
    vi.mocked(streamAssistReply).mockRejectedValue(new Error('provider down'))
    vi.mocked(createServiceCall).mockResolvedValue({
      id: 'sc-1', customer_id: 'c1', description: 'The oven will not heat.',
      status: 'OPEN', created_at: '2026-07-29T09:00:00Z',
    })
    vi.mocked(fetchPooledAvailability).mockResolvedValue({ slots: [] })

    renderPage()
    await screen.findByRole('heading', { name: /tell us what is wrong/i })
    await userEvent.type(await screen.findByRole('textbox'), 'The oven will not heat.')
    await userEvent.click(screen.getByRole('button', { name: /send/i }))
    await screen.findByRole('alert')

    await userEvent.click(screen.getByRole('button', { name: /open a service call instead/i }))

    expect(await screen.findByRole('heading', { name: /open a service call/i })).toBeInTheDocument()
    expect(screen.queryByRole('heading', { name: /tell us what is wrong/i })).toBeNull()

    await userEvent.type(screen.getByRole('textbox'), 'The oven will not heat.')
    await userEvent.click(screen.getByRole('button', { name: /^open service call$/i }))

    expect(await screen.findByRole('heading', { name: /next available slots/i })).toBeInTheDocument()
  })

  it('escapes to the classic form when the conversation cannot even be opened', async () => {
    vi.mocked(fetchUpcomingAppointments).mockResolvedValue({ items: [] })
    vi.mocked(fetchAssistStatus).mockResolvedValue({ enabled: true })
    vi.mocked(startConversation).mockRejectedValue(
      new ApiException(409, 'You already have a conversation open.'),
    )

    renderPage()
    await screen.findByRole('alert')

    await userEvent.click(screen.getByRole('button', { name: /open a service call instead/i }))

    expect(await screen.findByRole('heading', { name: /open a service call/i })).toBeInTheDocument()
    expect(screen.queryByRole('heading', { name: /tell us what is wrong/i })).toBeNull()
  })

  it('renders neither the chat nor the classic form while the assistant status is unresolved', async () => {
    vi.mocked(fetchUpcomingAppointments).mockResolvedValue({ items: [] })
    let resolveStatus: (value: { enabled: boolean }) => void = () => {}
    vi.mocked(fetchAssistStatus).mockReturnValue(
      new Promise((resolve) => { resolveStatus = resolve }),
    )

    renderPage()

    await screen.findByRole('heading', { name: /customer dashboard/i })
    expect(screen.queryByRole('heading', { name: /open a service call/i })).not.toBeInTheDocument()
    expect(screen.queryByRole('heading', { name: /tell us what is wrong/i })).not.toBeInTheDocument()

    resolveStatus({ enabled: false })
    expect(await screen.findByRole('heading', { name: /open a service call/i })).toBeInTheDocument()
  })
})
