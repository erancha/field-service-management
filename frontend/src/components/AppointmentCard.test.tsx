import { beforeEach, describe, expect, it, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { AppointmentCard } from './AppointmentCard.tsx'
import { fetchAvailability } from '../api/scheduling.ts'
import type { Appointment } from '../api/types.ts'

vi.mock('../api/scheduling.ts', () => ({
  fetchAvailability: vi.fn(),
  servicePhotoUrl: (serviceCallId: string, photoId: string, variant: string) =>
    `/api/service-calls/${serviceCallId}/photos/${photoId}?variant=${variant}`,
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
    // The API serializes statuses uppercase; tests must use the same casing to catch
    // case-sensitive comparisons in the component.
    status: 'SCHEDULED',
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

describe('AppointmentCard focused editing', () => {
  it('hides Reschedule and Cancel Appointment while editing details', async () => {
    render(
      <AppointmentCard
        appointment={makeAppointment({ details: 'Gate code 4321' })}
        onReschedule={vi.fn()}
        onCancel={vi.fn()}
        onAddDetails={vi.fn()}
      />,
    )

    await userEvent.click(screen.getByRole('button', { name: /edit details/i }))

    expect(screen.queryByRole('button', { name: /^reschedule$/i })).toBeNull()
    expect(screen.queryByRole('button', { name: /cancel appointment/i })).toBeNull()
    expect(screen.getByRole('button', { name: /save/i })).toBeInTheDocument()
  })

  it('hides Cancel Appointment while rescheduling', async () => {
    render(
      <AppointmentCard
        appointment={makeAppointment()}
        onReschedule={vi.fn()}
        onCancel={vi.fn()}
        onAddDetails={vi.fn()}
      />,
    )

    await userEvent.click(screen.getByRole('button', { name: /^reschedule$/i }))
    await screen.findByRole('button', { name: /–/ })

    expect(screen.queryByRole('button', { name: /cancel appointment/i })).toBeNull()
    expect(screen.queryByRole('button', { name: /edit details|add details/i })).toBeNull()
  })

  it('restores the action row when the edit is dismissed', async () => {
    render(
      <AppointmentCard
        appointment={makeAppointment({ details: 'Gate code 4321' })}
        onCancel={vi.fn()}
        onAddDetails={vi.fn()}
      />,
    )

    await userEvent.click(screen.getByRole('button', { name: /edit details/i }))
    await userEvent.click(screen.getByRole('button', { name: /^cancel$/i }))

    expect(screen.getByRole('button', { name: /edit details/i })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /cancel appointment/i })).toBeInTheDocument()
    expect(screen.queryByRole('textbox')).toBeNull()
  })
})

describe('AppointmentCard cancel confirmation', () => {
  it('asks for confirmation instead of cancelling on the first click', async () => {
    const onCancel = vi.fn()
    render(<AppointmentCard appointment={makeAppointment()} onCancel={onCancel} />)

    await userEvent.click(screen.getByRole('button', { name: /cancel appointment/i }))

    expect(onCancel).not.toHaveBeenCalled()
    expect(screen.getByRole('button', { name: /keep appointment/i })).toBeInTheDocument()
  })

  it('cancels only after the confirmation is accepted', async () => {
    const onCancel = vi.fn()
    const appointment = makeAppointment()
    render(<AppointmentCard appointment={appointment} onCancel={onCancel} />)

    await userEvent.click(screen.getByRole('button', { name: /^cancel appointment$/i }))
    await userEvent.click(screen.getByRole('button', { name: /yes, cancel appointment/i }))

    expect(onCancel).toHaveBeenCalledWith(appointment.id)
  })

  it('keeps the appointment and restores the actions when confirmation is dismissed', async () => {
    const onCancel = vi.fn()
    render(
      <AppointmentCard appointment={makeAppointment()} onReschedule={vi.fn()} onCancel={onCancel} />,
    )

    await userEvent.click(screen.getByRole('button', { name: /^cancel appointment$/i }))
    await userEvent.click(screen.getByRole('button', { name: /keep appointment/i }))

    expect(onCancel).not.toHaveBeenCalled()
    expect(screen.getByRole('button', { name: /^reschedule$/i })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /^cancel appointment$/i })).toBeInTheDocument()
  })
})

describe('AppointmentCard details', () => {
  it('labels the action Add Details when the appointment has none', () => {
    render(<AppointmentCard appointment={makeAppointment()} onAddDetails={vi.fn()} />)
    expect(screen.getByRole('button', { name: /add details/i })).toBeInTheDocument()
  })

  it('labels the action Edit Details and pre-fills the form with the existing text', async () => {
    render(
      <AppointmentCard
        appointment={makeAppointment({ details: 'Gate code 4321' })}
        onAddDetails={vi.fn()}
      />,
    )

    await userEvent.click(screen.getByRole('button', { name: /edit details/i }))
    expect(screen.getByRole('textbox')).toHaveValue('Gate code 4321')
  })

  it('saves the edited text rather than only the newly typed text', async () => {
    const onAddDetails = vi.fn()
    const appointment = makeAppointment({ details: 'Gate code 4321' })
    render(<AppointmentCard appointment={appointment} onAddDetails={onAddDetails} />)

    await userEvent.click(screen.getByRole('button', { name: /edit details/i }))
    const textarea = screen.getByRole('textbox')
    await userEvent.type(textarea, ', dog in the yard')
    await userEvent.click(screen.getByRole('button', { name: /save/i }))

    expect(onAddDetails).toHaveBeenCalledWith(
      appointment.id,
      'Gate code 4321, dog in the yard',
    )
  })
})

describe('AppointmentCard facts', () => {
  it('renders problem, names, and address when provided', () => {
    render(
      <AppointmentCard
        appointment={makeAppointment()}
        problem="Fix boiler"
        technicianName="Tara"
        customerName="Cara"
        address="12 Main St"
      />,
    )
    expect(screen.getByText('Fix boiler')).toBeInTheDocument()
    expect(screen.getByText(/Tara/)).toBeInTheDocument()
    expect(screen.getByText(/Cara/)).toBeInTheDocument()
    expect(screen.getByText(/12 Main St/)).toBeInTheDocument()
  })

  it('renders the summary layout the API sends, heading by heading', () => {
    const summary = [
      { heading: 'Problem', bullets: ['No picture, sound present'], fields: [] },
      { heading: 'Action items', bullets: ['Bring backlight strip parts'], fields: [] },
      { heading: 'Triage summary', bullets: [], fields: [['Equipment', 'LG 86NANO91VPA']] as [string, string][] },
      { heading: 'Steps ruled out', bullets: [], fields: [] },
    ]
    const { container } = render(
      <AppointmentCard appointment={makeAppointment()} problem="ignored text" summary={summary} />,
    )

    // One flat run of headings, no grouping above them, and a block the conversation gave nothing
    // for prints neither heading nor list — the calendar event renders exactly this shape.
    expect(
      Array.from(container.querySelectorAll('.triage-summary h4')).map((h) => h.textContent),
    ).toEqual(['Problem:', 'Action items:', 'Triage summary:'])
    expect(
      Array.from(container.querySelectorAll('.triage-summary li')).map((li) => li.textContent),
    ).toEqual([
      'No picture, sound present',
      'Bring backlight strip parts',
      'Equipment: LG 86NANO91VPA',
    ])
  })

  it('shows a hand-written description as the problem when there is no summary', () => {
    const { container } = render(
      <AppointmentCard appointment={makeAppointment()} problem="Boiler leaks" />,
    )

    expect(container.querySelector('.appointment-card__problem')?.textContent).toBe('Boiler leaks')
    expect(container.querySelector('.triage-summary')).toBeNull()
  })

  it('renders the From and To moments in the shared minute-precision local format', () => {
    const appointment = makeAppointment()
    render(<AppointmentCard appointment={appointment} />)
    // Derived with the same locale call the shared formatter uses, so the expectation holds in
    // any test-machine timezone.
    const asShown = (iso: string) =>
      new Date(iso).toLocaleString([], { dateStyle: 'medium', timeStyle: 'short' })
    expect(screen.getByText(asShown(appointment.start))).toBeInTheDocument()
    expect(screen.getByText(asShown(appointment.end))).toBeInTheDocument()
  })
})

describe('AppointmentCard photos', () => {
  it('renders each photo as a preview thumbnail that opens the original in a new tab', () => {
    const appointment = makeAppointment()
    render(
      <AppointmentCard
        appointment={appointment}
        photos={[{ id: 'p1', filename: 'plate.jpg', size_bytes: 3 }]}
      />,
    )

    const image = screen.getByRole('img', { name: 'plate.jpg' })
    expect(image).toHaveAttribute(
      'src',
      `/api/service-calls/${appointment.service_call_id}/photos/p1?variant=preview`,
    )
    const link = image.closest('a')
    expect(link).toHaveAttribute(
      'href',
      `/api/service-calls/${appointment.service_call_id}/photos/p1?variant=original`,
    )
    // Clicking shows the full image rather than saving a file, so the anchor must not carry a
    // download attribute — the route serves the original inline.
    expect(link).not.toHaveAttribute('download')
    expect(link).toHaveAttribute('target', '_blank')
    expect(link).toHaveAttribute('rel', 'noopener noreferrer')
  })

  it('renders no gallery without photos', () => {
    const { container } = render(<AppointmentCard appointment={makeAppointment()} />)
    expect(container.querySelector('.appointment-card__photos')).toBeNull()
  })
})

describe('AppointmentCard cancelled state', () => {
  it('offers no actions on a cancelled appointment', () => {
    render(
      <AppointmentCard
        appointment={makeAppointment({ status: 'CANCELLED' })}
        onReschedule={vi.fn()}
        onCancel={vi.fn()}
        onAddDetails={vi.fn()}
      />,
    )

    expect(screen.queryByRole('button')).toBeNull()
  })

  it('applies the cancelled styling modifier despite the uppercase API status', () => {
    const { container } = render(
      <AppointmentCard appointment={makeAppointment({ status: 'CANCELLED' })} />,
    )

    expect(container.querySelector('.appointment-card--cancelled')).not.toBeNull()
  })
})
