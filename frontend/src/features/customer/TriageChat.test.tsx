import { describe, expect, it, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { TriageChat } from './TriageChat.tsx'
import { ApiException } from '../../api/client.ts'
import type { TriageConversation } from '../../api/types.ts'

vi.mock('../../api/assist.ts', () => ({
  startConversation: vi.fn(),
  streamAssistReply: vi.fn(),
  endConversation: vi.fn(),
  listPastConversations: vi.fn(),
  fetchConversation: vi.fn(),
}))

const { startConversation, streamAssistReply, endConversation, listPastConversations, fetchConversation } =
  await import('../../api/assist.ts')

const EMPTY_CONVERSATION: TriageConversation = {
  id: 'c1',
  status: 'ACTIVE',
  service_call_id: null,
  messages: [],
}

beforeEach(() => {
  vi.mocked(startConversation).mockReset()
  vi.mocked(streamAssistReply).mockReset()
  vi.mocked(endConversation).mockReset()
  vi.mocked(fetchConversation).mockReset()
  vi.mocked(listPastConversations).mockReset()
  vi.mocked(listPastConversations).mockResolvedValue([])
})

describe('TriageChat', () => {
  it('rehydrates the stored conversation on mount', async () => {
    vi.mocked(startConversation).mockResolvedValue({
      ...EMPTY_CONVERSATION,
      messages: [
        { id: 'm1', role: 'CUSTOMER', text: 'The oven will not heat.', created_at: '' },
        { id: 'm2', role: 'ASSISTANT', text: 'Is the display lit?', created_at: '' },
      ],
    })

    render(<TriageChat onEscalated={() => {}} onGiveUp={() => {}} />)

    expect(await screen.findByText('The oven will not heat.')).toBeInTheDocument()
    expect(screen.getByText('Is the display lit?')).toBeInTheDocument()
  })

  it('shows the customer turn immediately and the reply as it streams', async () => {
    vi.mocked(startConversation).mockResolvedValue(EMPTY_CONVERSATION)
    vi.mocked(streamAssistReply).mockImplementation(async (_id, _text, onToken) => {
      onToken('Is ')
      onToken('it lit?')
      return { status: 'ACTIVE', service_call: null }
    })
    render(<TriageChat onEscalated={() => {}} onGiveUp={() => {}} />)
    await screen.findByRole('textbox')

    await userEvent.type(screen.getByRole('textbox'), 'It will not heat.')
    await userEvent.click(screen.getByRole('button', { name: /send/i }))

    expect(await screen.findByText('It will not heat.')).toBeInTheDocument()
    expect(await screen.findByText('Is it lit?')).toBeInTheDocument()
  })

  it('hands the created service call up when the assistant escalates', async () => {
    vi.mocked(startConversation).mockResolvedValue(EMPTY_CONVERSATION)
    vi.mocked(streamAssistReply).mockResolvedValue({
      status: 'ESCALATED',
      service_call: { id: 'sc-1', description: 'Equipment: Oven' },
    })
    const onEscalated = vi.fn()
    render(<TriageChat onEscalated={onEscalated} onGiveUp={() => {}} />)
    await screen.findByRole('textbox')

    await userEvent.type(screen.getByRole('textbox'), 'Still cold.')
    await userEvent.click(screen.getByRole('button', { name: /send/i }))

    await waitFor(() => expect(onEscalated).toHaveBeenCalledWith(
      expect.objectContaining({ id: 'sc-1', description: 'Equipment: Oven' }),
    ))
  })

  it('closes the whole exchange down to the restart button when the problem is solved', async () => {
    vi.mocked(startConversation).mockResolvedValue(EMPTY_CONVERSATION)
    vi.mocked(streamAssistReply).mockResolvedValue({ status: 'SOLVED', service_call: null })
    render(<TriageChat onEscalated={() => {}} onGiveUp={() => {}} />)
    await screen.findByRole('textbox')

    await userEvent.type(screen.getByRole('textbox'), 'That fixed it.')
    await userEvent.click(screen.getByRole('button', { name: /send/i }))

    expect(await screen.findByText(/no technician visit is needed/i)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /start a new conversation/i })).toBeInTheDocument()
    expect(screen.queryByRole('textbox')).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /end chat/i })).toBeNull()
    expect(screen.queryByText('That fixed it.')).toBeNull()
  })

  it('shows the backend detail and lets the customer resend after a rejected turn', async () => {
    vi.mocked(startConversation).mockResolvedValue(EMPTY_CONVERSATION)
    vi.mocked(streamAssistReply).mockRejectedValue(
      new ApiException(409, 'This conversation has already ended.'),
    )
    render(<TriageChat onEscalated={() => {}} onGiveUp={() => {}} />)
    await screen.findByRole('textbox')

    await userEvent.type(screen.getByRole('textbox'), 'hello')
    await userEvent.click(screen.getByRole('button', { name: /send/i }))

    expect(await screen.findByRole('alert')).toHaveTextContent('This conversation has already ended.')
    expect(screen.getByRole('textbox')).toHaveValue('hello')
    expect(screen.queryByText('hello', { selector: 'li' })).not.toBeInTheDocument()
  })

  it('falls back to a generic message when a turn fails for an unrecognised reason', async () => {
    vi.mocked(startConversation).mockResolvedValue(EMPTY_CONVERSATION)
    vi.mocked(streamAssistReply).mockRejectedValue(new Error('boom'))
    render(<TriageChat onEscalated={() => {}} onGiveUp={() => {}} />)
    await screen.findByRole('textbox')

    await userEvent.type(screen.getByRole('textbox'), 'hello')
    await userEvent.click(screen.getByRole('button', { name: /send/i }))

    expect(await screen.findByRole('alert')).toHaveTextContent(/assistant/i)
    expect(screen.getByRole('textbox')).toHaveValue('hello')
  })

  it('offers a way out to the classic form after a failed turn', async () => {
    vi.mocked(startConversation).mockResolvedValue(EMPTY_CONVERSATION)
    vi.mocked(streamAssistReply).mockRejectedValue(new Error('provider down'))
    const onGiveUp = vi.fn()
    render(<TriageChat onEscalated={() => {}} onGiveUp={onGiveUp} />)
    await screen.findByRole('textbox')

    await userEvent.type(screen.getByRole('textbox'), 'hello')
    await userEvent.click(screen.getByRole('button', { name: /send/i }))
    await screen.findByRole('alert')

    await userEvent.click(screen.getByRole('button', { name: /open a service call instead/i }))

    expect(onGiveUp).toHaveBeenCalled()
  })

  it('offers the same way out when the conversation never opens', async () => {
    vi.mocked(startConversation).mockRejectedValue(new Error('offline'))
    const onGiveUp = vi.fn()
    render(<TriageChat onEscalated={() => {}} onGiveUp={onGiveUp} />)
    await screen.findByRole('alert')

    await userEvent.click(screen.getByRole('button', { name: /open a service call instead/i }))

    expect(onGiveUp).toHaveBeenCalled()
  })

  it('hides the way out until a turn has actually failed', async () => {
    vi.mocked(startConversation).mockResolvedValue(EMPTY_CONVERSATION)
    render(<TriageChat onEscalated={() => {}} onGiveUp={() => {}} />)
    await screen.findByRole('textbox')

    expect(screen.queryByRole('button', { name: /open a service call instead/i })).toBeNull()
  })

  it('lets the customer open a fresh conversation after a solved one', async () => {
    vi.mocked(startConversation)
      .mockResolvedValueOnce({
        ...EMPTY_CONVERSATION,
        messages: [{ id: 'm1', role: 'CUSTOMER', text: 'The oven will not heat.', created_at: '' }],
      })
      .mockResolvedValueOnce({ ...EMPTY_CONVERSATION, id: 'c2' })
    vi.mocked(streamAssistReply).mockResolvedValue({ status: 'SOLVED', service_call: null })
    render(<TriageChat onEscalated={() => {}} onGiveUp={() => {}} />)
    await screen.findByRole('textbox')

    await userEvent.type(screen.getByRole('textbox'), 'That fixed it.')
    await userEvent.click(screen.getByRole('button', { name: /send/i }))
    await screen.findByText(/no technician visit is needed/i)

    await userEvent.click(screen.getByRole('button', { name: /start a new conversation/i }))

    expect(await screen.findByRole('textbox')).toBeInTheDocument()
    expect(screen.queryByText('The oven will not heat.')).toBeNull()
    expect(screen.queryByText(/no technician visit is needed/i)).toBeNull()
  })

  it('collapses an open past conversation when the customer sends a message', async () => {
    vi.mocked(listPastConversations).mockResolvedValue([{
      id: 'old',
      status: 'SOLVED',
      updated_at: '2026-07-24T09:00:00+00:00',
      opening_line: 'No hot water since this morning.',
    }])
    vi.mocked(fetchConversation).mockResolvedValue({
      id: 'old',
      status: 'SOLVED',
      service_call_id: null,
      messages: [{ id: 'm1', role: 'ASSISTANT', text: 'Is the pilot light on?', created_at: '' }],
    })
    vi.mocked(startConversation).mockResolvedValue(EMPTY_CONVERSATION)
    vi.mocked(streamAssistReply).mockResolvedValue({ status: 'ACTIVE', service_call: null })
    render(<TriageChat onEscalated={() => {}} onGiveUp={() => {}} />)
    await screen.findByRole('textbox')

    await userEvent.click(await screen.findByRole('button', { name: /past conversations/i }))
    await userEvent.click(screen.getByRole('button', { name: /no hot water/i }))
    expect(await screen.findByText('Is the pilot light on?')).toBeInTheDocument()

    await userEvent.type(screen.getByRole('textbox'), 'The oven will not heat.')
    await userEvent.click(screen.getByRole('button', { name: /^send$/i }))

    await waitFor(() =>
      expect(screen.queryByText('Is the pilot light on?')).not.toBeInTheDocument())
    expect(screen.getByRole('button', { name: /past conversations/i }))
      .toHaveAttribute('aria-expanded', 'false')
  })

  it('ends the conversation without booking anything when the customer closes the chat', async () => {
    vi.mocked(startConversation).mockResolvedValue({
      ...EMPTY_CONVERSATION,
      messages: [{ id: 'm1', role: 'CUSTOMER', text: 'The oven will not heat.', created_at: '' }],
    })
    vi.mocked(endConversation).mockResolvedValue({ ...EMPTY_CONVERSATION, status: 'ABANDONED' })
    const onEscalated = vi.fn()
    render(<TriageChat onEscalated={onEscalated} onGiveUp={() => {}} />)
    await screen.findByRole('textbox')

    await userEvent.click(screen.getByRole('button', { name: /end chat/i }))

    expect(await screen.findByText(/nothing has been booked/i)).toBeInTheDocument()
    expect(endConversation).toHaveBeenCalledWith('c1')
    expect(onEscalated).not.toHaveBeenCalled()
    expect(screen.queryByRole('textbox')).not.toBeInTheDocument()
    expect(screen.queryByText('The oven will not heat.')).toBeNull()
  })

  it('offers a fresh start after the assistant closes an off-topic conversation', async () => {
    vi.mocked(startConversation)
      .mockResolvedValueOnce(EMPTY_CONVERSATION)
      .mockResolvedValueOnce({ ...EMPTY_CONVERSATION, id: 'c2' })
    vi.mocked(streamAssistReply).mockResolvedValue({ status: 'ABANDONED', service_call: null })
    const onEscalated = vi.fn()
    render(<TriageChat onEscalated={onEscalated} onGiveUp={() => {}} />)
    await screen.findByRole('textbox')

    await userEvent.type(screen.getByRole('textbox'), 'Where should I stay in Rome?')
    await userEvent.click(screen.getByRole('button', { name: /^send$/i }))

    expect(await screen.findByText(/nothing has been booked/i)).toBeInTheDocument()
    expect(onEscalated).not.toHaveBeenCalled()

    await userEvent.click(screen.getByRole('button', { name: /start a new conversation/i }))

    expect(await screen.findByRole('textbox')).toBeInTheDocument()
  })

  it('reports a failed end without closing the composer', async () => {
    vi.mocked(startConversation).mockResolvedValue(EMPTY_CONVERSATION)
    vi.mocked(endConversation).mockRejectedValue(new Error('offline'))
    render(<TriageChat onEscalated={() => {}} onGiveUp={() => {}} />)
    await screen.findByRole('textbox')

    await userEvent.click(screen.getByRole('button', { name: /end chat/i }))

    expect(await screen.findByRole('alert')).toHaveTextContent(/could not/i)
    expect(screen.getByRole('textbox')).toBeInTheDocument()
  })

  it('lets the customer retry after the initial conversation load fails', async () => {
    vi.mocked(startConversation)
      .mockRejectedValueOnce(new Error('offline'))
      .mockResolvedValueOnce(EMPTY_CONVERSATION)
    render(<TriageChat onEscalated={() => {}} onGiveUp={() => {}} />)

    expect(await screen.findByRole('alert')).toHaveTextContent(/could not reach/i)
    expect(screen.queryByRole('textbox')).not.toBeInTheDocument()

    await userEvent.click(screen.getByRole('button', { name: /try again/i }))

    expect(await screen.findByRole('textbox')).toBeInTheDocument()
  })
})
