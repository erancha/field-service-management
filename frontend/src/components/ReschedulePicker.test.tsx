import { beforeEach, describe, expect, it, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { ReschedulePicker } from './ReschedulePicker.tsx'
import { fetchAvailability } from '../api/scheduling.ts'

vi.mock('../api/scheduling.ts', () => ({
  fetchAvailability: vi.fn(),
}))

const SLOTS = [
  { start: '2026-07-06T09:00:00+03:00', end: '2026-07-06T10:00:00+03:00' },
  { start: '2026-07-06T11:00:00+03:00', end: '2026-07-06T12:00:00+03:00' },
]

beforeEach(() => {
  vi.mocked(fetchAvailability).mockReset()
  vi.mocked(fetchAvailability).mockResolvedValue({ slots: SLOTS })
})

describe('ReschedulePicker', () => {
  it("fetches the appointment technician's availability over the search window", async () => {
    render(<ReschedulePicker technicianId="tech-1" onConfirm={vi.fn()} />)

    await screen.findAllByRole('button')
    expect(fetchAvailability).toHaveBeenCalledWith(
      expect.objectContaining({ technician_id: 'tech-1' }),
    )
    const params = vi.mocked(fetchAvailability).mock.calls[0][0]
    expect(params.date_from).toMatch(/^\d{4}-\d{2}-\d{2}$/)
    expect(params.date_to).toMatch(/^\d{4}-\d{2}-\d{2}$/)
  })

  it('offers the fetched slots and no free-form time inputs', async () => {
    const { container } = render(
      <ReschedulePicker technicianId="tech-1" onConfirm={vi.fn()} />,
    )

    const slotButtons = await screen.findAllByRole('button', { name: /–/ })
    expect(slotButtons).toHaveLength(2)
    expect(container.querySelector('input')).toBeNull()
  })

  it('confirms with the selected slot times', async () => {
    const onConfirm = vi.fn()
    render(<ReschedulePicker technicianId="tech-1" onConfirm={onConfirm} />)

    const [firstSlot] = await screen.findAllByRole('button', { name: /–/ })
    const confirm = screen.getByRole('button', { name: /confirm/i })
    expect(confirm).toBeDisabled()

    await userEvent.click(firstSlot)
    await userEvent.click(confirm)
    expect(onConfirm).toHaveBeenCalledWith(SLOTS[0].start, SLOTS[0].end)
  })

  it('says there are no slots when the technician is fully booked', async () => {
    vi.mocked(fetchAvailability).mockResolvedValue({ slots: [] })
    render(<ReschedulePicker technicianId="tech-1" onConfirm={vi.fn()} />)

    expect(await screen.findByText(/no available slots/i)).toBeInTheDocument()
  })

  it('shows the error when availability cannot be loaded', async () => {
    vi.mocked(fetchAvailability).mockRejectedValue(new Error('availability down'))
    render(<ReschedulePicker technicianId="tech-1" onConfirm={vi.fn()} />)

    expect(await screen.findByText('availability down')).toBeInTheDocument()
  })
})
