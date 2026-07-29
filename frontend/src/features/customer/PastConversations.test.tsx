import { describe, expect, it, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { PastConversations } from './PastConversations.tsx'
import type { TriageConversationSummary } from '../../api/types.ts'

vi.mock('../../api/assist.ts', () => ({
  listPastConversations: vi.fn(),
  fetchConversation: vi.fn(),
}))

const { listPastConversations, fetchConversation } = await import('../../api/assist.ts')

const SOLVED: TriageConversationSummary = {
  id: 'c1',
  status: 'SOLVED',
  updated_at: '2026-07-24T09:00:00+00:00',
  opening_line: 'No hot water since this morning.',
}

const ESCALATED: TriageConversationSummary = {
  id: 'c2',
  status: 'ESCALATED',
  updated_at: '2026-07-29T18:08:00+00:00',
  opening_line: 'The boiler is leaking.',
}

beforeEach(() => {
  vi.mocked(listPastConversations).mockReset()
  vi.mocked(fetchConversation).mockReset()
})

describe('PastConversations', () => {
  it('renders nothing when the customer has no ended conversations', async () => {
    vi.mocked(listPastConversations).mockResolvedValue([])

    const { container } = render(<PastConversations refreshKey={0} collapseKey={0} />)

    await waitFor(() => expect(listPastConversations).toHaveBeenCalled())
    expect(container).toBeEmptyDOMElement()
  })

  it('keeps the list collapsed until the customer asks for it', async () => {
    vi.mocked(listPastConversations).mockResolvedValue([ESCALATED, SOLVED])

    render(<PastConversations refreshKey={0} collapseKey={0} />)

    const toggle = await screen.findByRole('button', { name: 'Past conversations (2)' })
    expect(screen.queryByText('The boiler is leaking.')).not.toBeInTheDocument()

    await userEvent.click(toggle)

    expect(screen.getByText('The boiler is leaking.')).toBeInTheDocument()
    expect(screen.getByText('Service call opened')).toBeInTheDocument()
    expect(screen.getByText('Solved')).toBeInTheDocument()
  })

  it('fetches a transcript once and keeps it across reopenings', async () => {
    vi.mocked(listPastConversations).mockResolvedValue([SOLVED])
    vi.mocked(fetchConversation).mockResolvedValue({
      id: 'c1',
      status: 'SOLVED',
      service_call_id: null,
      messages: [
        { id: 'm1', role: 'CUSTOMER', text: 'No hot water since this morning.', created_at: '' },
        { id: 'm2', role: 'ASSISTANT', text: 'Is the pilot light on?', created_at: '' },
      ],
    })
    render(<PastConversations refreshKey={0} collapseKey={0} />)

    await userEvent.click(await screen.findByRole('button', { name: /past conversations/i }))
    const row = screen.getByRole('button', { name: /no hot water/i })

    await userEvent.click(row)
    expect(await screen.findByText('Is the pilot light on?')).toBeInTheDocument()

    await userEvent.click(row)
    expect(screen.queryByText('Is the pilot light on?')).not.toBeInTheDocument()

    await userEvent.click(row)
    expect(await screen.findByText('Is the pilot light on?')).toBeInTheDocument()
    expect(fetchConversation).toHaveBeenCalledTimes(1)
  })

  it('reloads the list when the refresh key changes', async () => {
    vi.mocked(listPastConversations).mockResolvedValue([SOLVED])
    const { rerender } = render(<PastConversations refreshKey={0} collapseKey={0} />)
    await screen.findByRole('button', { name: 'Past conversations (1)' })

    vi.mocked(listPastConversations).mockResolvedValue([ESCALATED, SOLVED])
    rerender(<PastConversations refreshKey={1} collapseKey={0} />)

    expect(await screen.findByRole('button', { name: 'Past conversations (2)' })).toBeInTheDocument()
  })

  it('collapses the section and any open transcript when the collapse key changes', async () => {
    vi.mocked(listPastConversations).mockResolvedValue([SOLVED])
    vi.mocked(fetchConversation).mockResolvedValue({
      id: 'c1',
      status: 'SOLVED',
      service_call_id: null,
      messages: [
        { id: 'm1', role: 'ASSISTANT', text: 'Is the pilot light on?', created_at: '' },
      ],
    })
    const { rerender } = render(<PastConversations refreshKey={0} collapseKey={0} />)
    await userEvent.click(await screen.findByRole('button', { name: /past conversations/i }))
    await userEvent.click(screen.getByRole('button', { name: /no hot water/i }))
    expect(await screen.findByText('Is the pilot light on?')).toBeInTheDocument()

    rerender(<PastConversations refreshKey={0} collapseKey={1} />)

    expect(screen.queryByText('Is the pilot light on?')).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /no hot water/i })).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: /past conversations/i }))
      .toHaveAttribute('aria-expanded', 'false')
  })

  it('reports a failed list without hiding the live chat', async () => {
    vi.mocked(listPastConversations).mockRejectedValue(new Error('offline'))

    render(<PastConversations refreshKey={0} collapseKey={0} />)

    expect(await screen.findByText('Could not load your past conversations.')).toBeInTheDocument()
  })

  it('reports a transcript that cannot be loaded', async () => {
    vi.mocked(listPastConversations).mockResolvedValue([SOLVED])
    vi.mocked(fetchConversation).mockRejectedValue(new Error('offline'))
    render(<PastConversations refreshKey={0} collapseKey={0} />)

    await userEvent.click(await screen.findByRole('button', { name: /past conversations/i }))
    await userEvent.click(screen.getByRole('button', { name: /no hot water/i }))

    expect(await screen.findByText('Could not load this conversation.')).toBeInTheDocument()
  })
})
