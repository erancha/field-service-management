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
  uploadTriagePhoto: vi.fn(),
  deleteTriagePhoto: vi.fn(),
  triagePhotoPreviewUrl: (conversationId: string, photoId: string) =>
    `/api/assist/conversations/${conversationId}/photos/${photoId}/preview`,
}))

const {
  startConversation,
  streamAssistReply,
  endConversation,
  listPastConversations,
  fetchConversation,
  uploadTriagePhoto,
  deleteTriagePhoto,
} = await import('../../api/assist.ts')

const EMPTY_CONVERSATION: TriageConversation = {
  id: 'c1',
  status: 'ACTIVE',
  service_call_id: null,
  messages: [],
  pending_photos: [],
}

/** A reply asking a yes/no question, and the span the backend reports bounding that question. */
const YES_NO_REPLY = 'Power is fine. Is the breaker on?'
const YES_NO_SPAN = { start: 15, end: 33 }

beforeEach(() => {
  vi.mocked(startConversation).mockReset()
  vi.mocked(streamAssistReply).mockReset()
  vi.mocked(endConversation).mockReset()
  vi.mocked(fetchConversation).mockReset()
  vi.mocked(listPastConversations).mockReset()
  vi.mocked(listPastConversations).mockResolvedValue([])
  vi.mocked(uploadTriagePhoto).mockReset()
  vi.mocked(deleteTriagePhoto).mockReset()
  vi.mocked(deleteTriagePhoto).mockResolvedValue(undefined)
})

/**
 * The file input sits behind the composer's Attach photos toggle, which starts closed. Callers
 * that attach twice in one test find it already open the second time, so this reveals rather than
 * toggles.
 */
async function openAttach() {
  const toggle = screen.getByRole('button', { name: /attach photos/i })
  if (toggle.getAttribute('aria-expanded') === 'false') await userEvent.click(toggle)
  return screen.getByLabelText(/attach photos/i)
}

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

  it('holds focus in the composer on arrival and again after a send', async () => {
    vi.mocked(startConversation).mockResolvedValue(EMPTY_CONVERSATION)
    vi.mocked(streamAssistReply).mockResolvedValue({ sources: [], status: 'ACTIVE', service_call: null, question: null })
    render(<TriageChat onEscalated={() => {}} onGiveUp={() => {}} />)

    const composer = await screen.findByRole('textbox')
    await waitFor(() => expect(composer).toHaveFocus())

    await userEvent.type(composer, 'It will not heat.')
    await userEvent.click(screen.getByRole('button', { name: /send/i }))

    await waitFor(() => expect(composer).toHaveFocus())
  })

  it('shows the customer turn immediately and the reply as it streams', async () => {
    vi.mocked(startConversation).mockResolvedValue(EMPTY_CONVERSATION)
    vi.mocked(streamAssistReply).mockImplementation(async (_id, _text, _photoIds, onToken) => {
      onToken('Is ')
      onToken('it lit?')
      return { sources: [], status: 'ACTIVE', service_call: null, question: null }
    })
    render(<TriageChat onEscalated={() => {}} onGiveUp={() => {}} />)
    await screen.findByRole('textbox')

    await userEvent.type(screen.getByRole('textbox'), 'It will not heat.')
    await userEvent.click(screen.getByRole('button', { name: /send/i }))

    expect(await screen.findByText('It will not heat.')).toBeInTheDocument()
    expect(await screen.findByText('Is it lit?')).toBeInTheDocument()
  })

  it('offers the documents a turn matched, opening each in a new tab', async () => {
    vi.mocked(startConversation).mockResolvedValue(EMPTY_CONVERSATION)
    vi.mocked(streamAssistReply).mockImplementation(async (_id, _text, _photoIds, onToken) => {
      onToken('Check the photo eye.')
      return {
        status: 'ACTIVE',
        service_call: null,
        question: null,
        sources: [{ id: 'doc-1', filename: 'elevators.pdf', page: 213 }],
      }
    })
    render(<TriageChat onEscalated={() => {}} onGiveUp={() => {}} />)
    await screen.findByRole('textbox')

    await userEvent.type(screen.getByRole('textbox'), 'The doors keep reopening.')
    await userEvent.click(screen.getByRole('button', { name: /send/i }))

    const link = await screen.findByRole('link', { name: 'elevators.pdf, page 213' })
    expect(link).toHaveAttribute('href', '/api/kb/documents/doc-1/content#page=213')
    expect(link).toHaveAttribute('target', '_blank')
    expect(link).toHaveAttribute('rel', 'noopener noreferrer')
  })

  it('offers no document when the turn matched nothing well enough', async () => {
    vi.mocked(startConversation).mockResolvedValue(EMPTY_CONVERSATION)
    vi.mocked(streamAssistReply).mockImplementation(async (_id, _text, _photoIds, onToken) => {
      onToken('Tell me more.')
      return { sources: [], status: 'ACTIVE', service_call: null, question: null }
    })
    render(<TriageChat onEscalated={() => {}} onGiveUp={() => {}} />)
    await screen.findByRole('textbox')

    await userEvent.type(screen.getByRole('textbox'), 'What time does the office open?')
    await userEvent.click(screen.getByRole('button', { name: /send/i }))

    expect(await screen.findByText('Tell me more.')).toBeInTheDocument()
    expect(screen.queryByRole('link')).toBeNull()
    expect(screen.queryByText(/knowledge base/i)).toBeNull()
  })

  it('hands the created service call up when the assistant escalates', async () => {
    vi.mocked(startConversation).mockResolvedValue(EMPTY_CONVERSATION)
    vi.mocked(streamAssistReply).mockResolvedValue({
      status: 'ESCALATED',
      service_call: { id: 'sc-1', description: 'Equipment: Oven' },
      question: null,
      sources: [],
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

  it('emphasises the question the buttons answer, at the offsets the backend reported', async () => {
    vi.mocked(startConversation).mockResolvedValue(EMPTY_CONVERSATION)
    vi.mocked(streamAssistReply).mockImplementation(async (_id, _text, _photoIds, onToken) => {
      onToken(YES_NO_REPLY)
      return { sources: [], status: 'ACTIVE', service_call: null, question: YES_NO_SPAN }
    })
    render(<TriageChat onEscalated={() => {}} onGiveUp={() => {}} />)
    await screen.findByRole('textbox')

    await userEvent.type(screen.getByRole('textbox'), 'It will not heat.')
    await userEvent.click(screen.getByRole('button', { name: /^send$/i }))

    const question = await screen.findByText('Is the breaker on?')
    expect(question.tagName).toBe('STRONG')
    expect(screen.getByText(/Power is fine\./)).toBeInTheDocument()
  })

  it('drops the emphasis once the question has been answered', async () => {
    vi.mocked(startConversation).mockResolvedValue(EMPTY_CONVERSATION)
    vi.mocked(streamAssistReply)
      .mockImplementationOnce(async (_id, _text, _photoIds, onToken) => {
        onToken(YES_NO_REPLY)
        return { sources: [], status: 'ACTIVE', service_call: null, question: YES_NO_SPAN }
      })
      .mockImplementationOnce(async (_id, _text, _photoIds, onToken) => {
        onToken('Then the fault is downstream.')
        return { sources: [], status: 'ACTIVE', service_call: null, question: null }
      })
    render(<TriageChat onEscalated={() => {}} onGiveUp={() => {}} />)
    await screen.findByRole('textbox')
    await userEvent.type(screen.getByRole('textbox'), 'It will not heat.')
    await userEvent.click(screen.getByRole('button', { name: /^send$/i }))
    expect((await screen.findByText('Is the breaker on?')).tagName).toBe('STRONG')

    await userEvent.click(screen.getByRole('button', { name: /^yes$/i }))

    await screen.findByText('Then the fault is downstream.')
    expect(screen.queryByText('Is the breaker on?')).toBeNull()
  })

  it('sends a tapped answer as its own turn, the one-tap path', async () => {
    vi.mocked(startConversation).mockResolvedValue(EMPTY_CONVERSATION)
    vi.mocked(streamAssistReply)
      .mockResolvedValueOnce({ sources: [], status: 'ACTIVE', service_call: null, question: YES_NO_SPAN })
      .mockResolvedValueOnce({ sources: [], status: 'ACTIVE', service_call: null, question: null })
    render(<TriageChat onEscalated={() => {}} onGiveUp={() => {}} />)
    await screen.findByRole('textbox')
    await userEvent.type(screen.getByRole('textbox'), 'It will not heat.')
    await userEvent.click(screen.getByRole('button', { name: /^send$/i }))

    await userEvent.click(await screen.findByRole('button', { name: /^yes$/i }))

    expect(streamAssistReply).toHaveBeenLastCalledWith('c1', 'Yes', [], expect.any(Function))
    expect(await screen.findByText('Yes', { selector: 'li' })).toBeInTheDocument()
  })

  it('holds a tapped answer in the composer when the customer clears Send', async () => {
    vi.mocked(startConversation).mockResolvedValue(EMPTY_CONVERSATION)
    vi.mocked(streamAssistReply)
      .mockResolvedValueOnce({ sources: [], status: 'ACTIVE', service_call: null, question: YES_NO_SPAN })
      .mockResolvedValueOnce({ sources: [], status: 'ACTIVE', service_call: null, question: null })
    render(<TriageChat onEscalated={() => {}} onGiveUp={() => {}} />)
    await screen.findByRole('textbox')
    await userEvent.type(screen.getByRole('textbox'), 'It will not heat.')
    await userEvent.click(screen.getByRole('button', { name: /^send$/i }))

    const sendOnTap = await screen.findByRole('checkbox', { name: /^send$/i })
    expect(sendOnTap).toBeChecked()
    await userEvent.click(sendOnTap)
    await userEvent.click(screen.getByRole('button', { name: /^yes$/i }))

    expect(streamAssistReply).toHaveBeenCalledTimes(1)
    expect(screen.getByRole('textbox')).toHaveValue('Yes')
    await waitFor(() => expect(screen.getByRole('textbox')).toHaveFocus())

    await userEvent.type(screen.getByRole('textbox'), ', on the control box')
    await userEvent.click(screen.getByRole('button', { name: /^send$/i }))

    expect(streamAssistReply).toHaveBeenLastCalledWith(
      'c1', 'Yes, on the control box', [], expect.any(Function),
    )
  })

  it('carries text typed before the tap into the answer rather than stranding it', async () => {
    vi.mocked(startConversation).mockResolvedValue(EMPTY_CONVERSATION)
    vi.mocked(streamAssistReply)
      .mockResolvedValueOnce({ sources: [], status: 'ACTIVE', service_call: null, question: YES_NO_SPAN })
      .mockResolvedValueOnce({ sources: [], status: 'ACTIVE', service_call: null, question: null })
    render(<TriageChat onEscalated={() => {}} onGiveUp={() => {}} />)
    await screen.findByRole('textbox')
    await userEvent.type(screen.getByRole('textbox'), 'It will not heat.')
    await userEvent.click(screen.getByRole('button', { name: /^send$/i }))
    await screen.findByRole('button', { name: /^no$/i })

    await userEvent.type(screen.getByRole('textbox'), 'only the mast one is lit')
    await userEvent.click(screen.getByRole('button', { name: /^no$/i }))

    expect(streamAssistReply).toHaveBeenLastCalledWith(
      'c1', 'No, only the mast one is lit', [], expect.any(Function),
    )
    expect(screen.getByRole('textbox')).toHaveValue('')
  })

  it('retires the quick replies once one has been tapped', async () => {
    vi.mocked(startConversation).mockResolvedValue(EMPTY_CONVERSATION)
    vi.mocked(streamAssistReply)
      .mockResolvedValueOnce({ sources: [], status: 'ACTIVE', service_call: null, question: YES_NO_SPAN })
    render(<TriageChat onEscalated={() => {}} onGiveUp={() => {}} />)
    await screen.findByRole('textbox')
    await userEvent.type(screen.getByRole('textbox'), 'It will not heat.')
    await userEvent.click(screen.getByRole('button', { name: /^send$/i }))

    await userEvent.click(await screen.findByRole('button', { name: /^yes$/i }))

    await waitFor(() => expect(screen.queryByRole('button', { name: /^yes$/i })).toBeNull())
    expect(screen.queryByRole('button', { name: /^no$/i })).toBeNull()
  })

  it('keeps the quick replies out of an ordinary exchange', async () => {
    vi.mocked(startConversation).mockResolvedValue(EMPTY_CONVERSATION)
    vi.mocked(streamAssistReply).mockResolvedValue(
      { sources: [], status: 'ACTIVE', service_call: null, question: null },
    )
    render(<TriageChat onEscalated={() => {}} onGiveUp={() => {}} />)
    await screen.findByRole('textbox')

    await userEvent.type(screen.getByRole('textbox'), 'It will not heat.')
    await userEvent.click(screen.getByRole('button', { name: /^send$/i }))

    await waitFor(() => expect(screen.getByRole('textbox')).toHaveFocus())
    expect(screen.queryByRole('button', { name: /^yes$/i })).toBeNull()
    expect(screen.queryByRole('button', { name: /^no$/i })).toBeNull()
  })

  it('closes the whole exchange down to the restart button when the problem is solved', async () => {
    vi.mocked(startConversation).mockResolvedValue(EMPTY_CONVERSATION)
    vi.mocked(streamAssistReply).mockResolvedValue({ sources: [], status: 'SOLVED', service_call: null, question: null })
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
    vi.mocked(streamAssistReply).mockResolvedValue({ sources: [], status: 'SOLVED', service_call: null, question: null })
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
      pending_photos: [],
    })
    vi.mocked(startConversation).mockResolvedValue(EMPTY_CONVERSATION)
    vi.mocked(streamAssistReply).mockResolvedValue({ sources: [], status: 'ACTIVE', service_call: null, question: null })
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
    vi.mocked(streamAssistReply).mockResolvedValue({ sources: [], status: 'ABANDONED', service_call: null, question: null })
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

  it('keeps the file picker behind the Attach photos toggle, open and shut', async () => {
    vi.mocked(startConversation).mockResolvedValue(EMPTY_CONVERSATION)
    render(<TriageChat onEscalated={() => {}} onGiveUp={() => {}} />)
    await screen.findByRole('textbox')
    const toggle = screen.getByRole('button', { name: /attach photos/i })

    expect(toggle).toHaveAttribute('aria-expanded', 'false')
    expect(screen.queryByLabelText(/attach photos/i)).toBeNull()

    await userEvent.click(toggle)
    expect(toggle).toHaveAttribute('aria-expanded', 'true')
    expect(screen.getByLabelText(/attach photos/i)).toBeInTheDocument()

    await userEvent.click(toggle)
    expect(toggle).toHaveAttribute('aria-expanded', 'false')
    expect(screen.queryByLabelText(/attach photos/i)).toBeNull()
  })

  it('uploads a valid photo and sends its id with the next turn', async () => {
    vi.mocked(startConversation).mockResolvedValue(EMPTY_CONVERSATION)
    vi.mocked(uploadTriagePhoto).mockResolvedValue({ id: 'p1', filename: 'plate.jpg', size_bytes: 3 })
    vi.mocked(streamAssistReply).mockResolvedValue({ sources: [], status: 'ACTIVE', service_call: null, question: null })
    render(<TriageChat onEscalated={() => {}} onGiveUp={() => {}} />)
    await screen.findByRole('textbox')

    const file = new File(['x'], 'plate.jpg', { type: 'image/jpeg' })
    await userEvent.upload(await openAttach(), file)
    await userEvent.type(screen.getByRole('textbox'), 'Here it is.')
    await userEvent.click(screen.getByRole('button', { name: /^send$/i }))

    expect(streamAssistReply).toHaveBeenCalledWith('c1', 'Here it is.', ['p1'], expect.any(Function))
    const sentPhoto = await screen.findByAltText('plate.jpg')
    expect(sentPhoto).toHaveAttribute('src', '/api/assist/conversations/c1/photos/p1/preview')
  })

  it('shows an upload note while a photo is uploading and a sent-with-next note once it lands', async () => {
    vi.mocked(startConversation).mockResolvedValue(EMPTY_CONVERSATION)
    let resolveUpload: (photo: { id: string; filename: string; size_bytes: number }) => void
    vi.mocked(uploadTriagePhoto).mockReturnValue(
      new Promise((resolve) => { resolveUpload = resolve }),
    )
    render(<TriageChat onEscalated={() => {}} onGiveUp={() => {}} />)
    await screen.findByRole('textbox')

    const file = new File(['x'], 'plate.jpg', { type: 'image/jpeg' })
    await userEvent.upload(await openAttach(), file)

    expect(await screen.findByText('Uploading photo…')).toBeInTheDocument()
    resolveUpload!({ id: 'p1', filename: 'plate.jpg', size_bytes: 3 })

    expect(await screen.findByText('Attached — will be sent with your next message.'))
      .toBeInTheDocument()
  })

  it('rejects an oversized photo before any upload', async () => {
    vi.mocked(startConversation).mockResolvedValue(EMPTY_CONVERSATION)
    render(<TriageChat onEscalated={() => {}} onGiveUp={() => {}} />)
    await screen.findByRole('textbox')

    const oversized = new File(['x'.repeat(5 * 1024 * 1024 + 1)], 'big.jpg', { type: 'image/jpeg' })
    await userEvent.upload(await openAttach(), oversized)

    expect(await screen.findByRole('alert')).toHaveTextContent(/5 MB or less/i)
    expect(uploadTriagePhoto).not.toHaveBeenCalled()
  })

  it('rejects a non-image file before any upload', async () => {
    vi.mocked(startConversation).mockResolvedValue(EMPTY_CONVERSATION)
    render(<TriageChat onEscalated={() => {}} onGiveUp={() => {}} />)
    await screen.findByRole('textbox')

    // The composer's own type check is the target here, not the input's browser-level `accept`
    // filter (which user-event applies by default and would silently drop the file beforehand).
    const user = userEvent.setup({ applyAccept: false })
    const notes = new File(['x'], 'notes.txt', { type: 'text/plain' })
    await user.upload(await openAttach(), notes)

    expect(await screen.findByRole('alert')).toHaveTextContent(/JPEG, PNG, or WebP/i)
    expect(uploadTriagePhoto).not.toHaveBeenCalled()
  })

  it('rejects attaching beyond five photos', async () => {
    vi.mocked(startConversation).mockResolvedValue(EMPTY_CONVERSATION)
    render(<TriageChat onEscalated={() => {}} onGiveUp={() => {}} />)
    await screen.findByRole('textbox')

    const files = Array.from({ length: 6 }, (_, i) =>
      new File(['x'], `photo${i}.jpg`, { type: 'image/jpeg' }))
    await userEvent.upload(await openAttach(), files)

    expect(await screen.findByRole('alert')).toHaveTextContent(/5/)
    expect(uploadTriagePhoto).not.toHaveBeenCalled()
  })

  it("shows the server's rejection message on upload failure", async () => {
    vi.mocked(startConversation).mockResolvedValue(EMPTY_CONVERSATION)
    vi.mocked(uploadTriagePhoto).mockRejectedValue(new ApiException(409, 'This conversation already has 5 photos.'))
    render(<TriageChat onEscalated={() => {}} onGiveUp={() => {}} />)
    await screen.findByRole('textbox')

    const file = new File(['x'], 'plate.jpg', { type: 'image/jpeg' })
    await userEvent.upload(await openAttach(), file)

    expect(await screen.findByRole('alert')).toHaveTextContent('This conversation already has 5 photos.')
  })

  it('clears pending photos after a delivered turn and keeps them on failure', async () => {
    vi.mocked(startConversation).mockResolvedValue(EMPTY_CONVERSATION)
    vi.mocked(uploadTriagePhoto).mockResolvedValue({ id: 'p1', filename: 'plate.jpg', size_bytes: 3 })
    vi.mocked(streamAssistReply).mockResolvedValue({ sources: [], status: 'ACTIVE', service_call: null, question: null })
    render(<TriageChat onEscalated={() => {}} onGiveUp={() => {}} />)
    await screen.findByRole('textbox')

    const file = new File(['x'], 'plate.jpg', { type: 'image/jpeg' })
    await userEvent.upload(await openAttach(), file)
    expect(await screen.findByRole('button', { name: /remove plate.jpg/i })).toBeInTheDocument()

    await userEvent.type(screen.getByRole('textbox'), 'Here it is.')
    await userEvent.click(screen.getByRole('button', { name: /^send$/i }))

    await waitFor(() =>
      expect(screen.queryByRole('button', { name: /remove plate.jpg/i })).not.toBeInTheDocument())

    vi.mocked(uploadTriagePhoto).mockResolvedValue({ id: 'p2', filename: 'leak.jpg', size_bytes: 3 })
    vi.mocked(streamAssistReply).mockRejectedValue(new Error('provider down'))
    const nextPhoto = new File(['x'], 'leak.jpg', { type: 'image/jpeg' })
    await userEvent.upload(await openAttach(), nextPhoto)
    expect(await screen.findByRole('button', { name: /remove leak.jpg/i })).toBeInTheDocument()

    await userEvent.type(screen.getByRole('textbox'), 'Still leaking.')
    await userEvent.click(screen.getByRole('button', { name: /^send$/i }))
    await screen.findByRole('alert')

    expect(screen.getByRole('button', { name: /remove leak.jpg/i })).toBeInTheDocument()
  })

  it('restores pending photos left over from before a reload', async () => {
    vi.mocked(startConversation).mockResolvedValue({
      ...EMPTY_CONVERSATION,
      pending_photos: [{ id: 'p1', filename: 'plate.jpg', size_bytes: 3 }],
    })
    render(<TriageChat onEscalated={() => {}} onGiveUp={() => {}} />)

    expect(await screen.findByText('Attached — will be sent with your next message.'))
      .toBeInTheDocument()
    expect(screen.getByRole('button', { name: /remove plate.jpg/i })).toBeInTheDocument()
  })

  it('removes a pending photo on the server when the customer drops it', async () => {
    vi.mocked(startConversation).mockResolvedValue({
      ...EMPTY_CONVERSATION,
      pending_photos: [{ id: 'p1', filename: 'plate.jpg', size_bytes: 3 }],
    })
    render(<TriageChat onEscalated={() => {}} onGiveUp={() => {}} />)
    const removeButton = await screen.findByRole('button', { name: /remove plate.jpg/i })

    await userEvent.click(removeButton)

    expect(deleteTriagePhoto).toHaveBeenCalledWith('c1', 'p1')
    await waitFor(() =>
      expect(screen.queryByRole('button', { name: /remove plate.jpg/i })).not.toBeInTheDocument())
  })

  it('keeps the pending photo and reports an error when removal fails', async () => {
    vi.mocked(startConversation).mockResolvedValue({
      ...EMPTY_CONVERSATION,
      pending_photos: [{ id: 'p1', filename: 'plate.jpg', size_bytes: 3 }],
    })
    vi.mocked(deleteTriagePhoto).mockRejectedValue(new Error('offline'))
    render(<TriageChat onEscalated={() => {}} onGiveUp={() => {}} />)
    const removeButton = await screen.findByRole('button', { name: /remove plate.jpg/i })

    await userEvent.click(removeButton)

    expect(await screen.findByRole('alert')).toHaveTextContent(/could not be removed/i)
    expect(screen.getByRole('button', { name: /remove plate.jpg/i })).toBeInTheDocument()
  })

  it('lets a photo-only turn be sent with an empty draft', async () => {
    vi.mocked(startConversation).mockResolvedValue({
      ...EMPTY_CONVERSATION,
      pending_photos: [{ id: 'p1', filename: 'plate.jpg', size_bytes: 3 }],
    })
    vi.mocked(streamAssistReply).mockResolvedValue({ sources: [], status: 'ACTIVE', service_call: null, question: null })
    render(<TriageChat onEscalated={() => {}} onGiveUp={() => {}} />)
    await screen.findByRole('button', { name: /remove plate.jpg/i })

    const sendButton = screen.getByRole('button', { name: /^send$/i })
    expect(sendButton).toBeEnabled()

    await userEvent.click(sendButton)

    expect(streamAssistReply).toHaveBeenCalledWith('c1', '', ['p1'], expect.any(Function))
  })

  it('disables send with neither a draft nor a pending photo', async () => {
    vi.mocked(startConversation).mockResolvedValue(EMPTY_CONVERSATION)
    render(<TriageChat onEscalated={() => {}} onGiveUp={() => {}} />)
    await screen.findByRole('textbox')

    expect(screen.getByRole('button', { name: /^send$/i })).toBeDisabled()
  })
})
