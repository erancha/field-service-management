import { ApiException, apiGet, apiPost } from './client.ts'
import type {
  AssistStatus,
  TriageConversation,
  TriageConversationSummary,
  TriageTurnResult,
} from './types.ts'

const BASE = '/api/assist'

export async function fetchAssistStatus(): Promise<AssistStatus> {
  return apiGet<AssistStatus>(`${BASE}/status`)
}

export async function startConversation(): Promise<TriageConversation> {
  return apiPost<TriageConversation>(`${BASE}/conversations`, {})
}

/** The customer's ended conversations, newest first; the live one is never among them. */
export async function listPastConversations(): Promise<TriageConversationSummary[]> {
  const body = await apiGet<{ conversations: TriageConversationSummary[] }>(`${BASE}/conversations`)
  return body.conversations
}

export async function fetchConversation(id: string): Promise<TriageConversation> {
  return apiGet<TriageConversation>(`${BASE}/conversations/${id}`)
}

/** Closes the conversation at the customer's request; no service call is opened. */
export async function endConversation(id: string): Promise<TriageConversation> {
  return apiPost<TriageConversation>(`${BASE}/conversations/${id}/end`, {})
}

interface SseFrame {
  name: string
  payload: Record<string, unknown>
}

function parseFrame(frame: string): SseFrame | null {
  let name: string | null = null
  let data: string | null = null
  for (const line of frame.split('\n')) {
    if (line.startsWith('event: ')) name = line.slice('event: '.length)
    else if (line.startsWith('data: ')) data = line.slice('data: '.length)
  }
  if (name === null || data === null) return null
  return { name, payload: JSON.parse(data) }
}

/**
 * Sends a customer turn and streams the assistant's reply as it is generated.
 *
 * The reply is a Server-Sent Events body on a POST request; the browser EventSource API only
 * issues GET requests, so it cannot read this response and the stream is decoded manually
 * instead. Frames can split across chunk boundaries, so bytes are buffered and only parsed once
 * a complete blank-line-terminated frame has arrived.
 *
 * The backend sends response headers before the model runs, so a provider failure mid-turn ends
 * the stream with no `done` frame and no other error signal. That case is a failed turn, not a
 * partial success, so it is surfaced as a rejection rather than returning whatever tokens arrived.
 */
export async function streamAssistReply(
  conversationId: string,
  text: string,
  onToken: (token: string) => void,
): Promise<TriageTurnResult> {
  const response = await fetch(`${BASE}/conversations/${conversationId}/messages`, {
    method: 'POST',
    credentials: 'include',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ text }),
  })

  if (!response.ok) {
    const body = await response.json().catch(() => ({}))
    throw new ApiException(response.status, body.detail ?? `HTTP ${response.status}`)
  }

  const reader = response.body?.getReader()
  if (!reader) throw new Error('The assistant returned an empty response')

  const decoder = new TextDecoder()
  let buffer = ''
  let result: TriageTurnResult | null = null

  for (;;) {
    const { done, value } = await reader.read()
    if (done) break
    buffer += decoder.decode(value, { stream: true })

    let split = buffer.indexOf('\n\n')
    while (split !== -1) {
      const frame = buffer.slice(0, split)
      buffer = buffer.slice(split + 2)
      const event = parseFrame(frame)
      if (event?.name === 'token') onToken(event.payload.text as string)
      if (event?.name === 'done') result = event.payload as unknown as TriageTurnResult
      split = buffer.indexOf('\n\n')
    }
  }

  if (result === null) throw new Error('The assistant stream ended without completing the turn')
  return result
}
