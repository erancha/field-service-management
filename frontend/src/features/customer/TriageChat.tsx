import { useEffect, useRef, useState } from 'react'
import { ApiException } from '../../api/client.ts'
import { endConversation, startConversation, streamAssistReply } from '../../api/assist.ts'
import type {
  ServiceCall,
  TriageEndedStatus,
  TriageMessage,
  TriageStatus,
} from '../../api/types.ts'
import { Button } from '../../components/Button.tsx'
import { ErrorBanner } from '../../components/ErrorBanner.tsx'
import { ChatTurns } from './ChatTurns.tsx'
import { PastConversations } from './PastConversations.tsx'

const MAX_MESSAGE_CHARS = 4000

/**
 * How each ending is reported once the composer is gone.
 *
 * ESCALATED is here for completeness of the ending set; the customer page swaps this chat for the
 * booking flow on escalation, so that line is not normally reached.
 */
const ENDING_NOTE: Record<TriageEndedStatus, string> = {
  SOLVED: 'Glad that sorted it — no technician visit is needed.',
  ABANDONED: 'This chat is closed — nothing has been booked.',
  ESCALATED: 'A service call is open — pick a visit slot to finish booking it.',
}

interface TriageChatProps {
  onEscalated: (serviceCall: ServiceCall) => void
  /** Hands the customer to the classic service-call form; the chat cannot recover on its own. */
  onGiveUp: () => void
}

/**
 * Surfaces the backend's detail when it is customer-safe text (an ApiException, e.g.
 * "conversation already ended" or "assistant not configured"); FastAPI's own validation errors
 * carry a list `detail`, not a string, and any other rejection (network failure, or the assist
 * client's own "stream ended without completing the turn") is internal wording the customer
 * should not see, so the caller-supplied fallback is used instead.
 */
function safeErrorMessage(err: unknown, fallback: string): string {
  if (err instanceof ApiException && typeof err.detail === 'string') return err.detail
  return fallback
}

export function TriageChat({ onEscalated, onGiveUp }: TriageChatProps) {
  const [conversationId, setConversationId] = useState<string | null>(null)
  const [messages, setMessages] = useState<TriageMessage[]>([])
  const [streaming, setStreaming] = useState('')
  const [status, setStatus] = useState<TriageStatus>('ACTIVE')
  const [draft, setDraft] = useState('')
  const [sending, setSending] = useState(false)
  const [ending, setEnding] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [initError, setInitError] = useState<string | null>(null)
  const [attempt, setAttempt] = useState(0)
  const [historyKey, setHistoryKey] = useState(0)
  const [collapseKey, setCollapseKey] = useState(0)
  const endRef = useRef<HTMLDivElement>(null)
  const nextLocalId = useRef(0)

  useEffect(() => {
    let cancelled = false
    setInitError(null)
    startConversation()
      .then((conversation) => {
        if (cancelled) return
        setConversationId(conversation.id)
        setMessages(conversation.messages)
        setStatus(conversation.status)
      })
      .catch((err) => {
        if (!cancelled) setInitError(safeErrorMessage(err, 'Could not reach the assistant'))
      })
    return () => { cancelled = true }
  }, [attempt])

  useEffect(() => { endRef.current?.scrollIntoView({ block: 'end' }) }, [messages, streaming])

  async function handleSend(e: React.FormEvent) {
    e.preventDefault()
    if (conversationId === null) return
    const text = draft.trim()
    setError(null)
    setDraft('')
    setSending(true)
    // The live exchange is what the customer is now watching; history folds out of its way.
    setCollapseKey((n) => n + 1)
    const optimisticId = `local-${nextLocalId.current++}`
    setMessages((prior) => [
      ...prior,
      { id: optimisticId, role: 'CUSTOMER', text, created_at: '' },
    ])

    let reply = ''
    try {
      const result = await streamAssistReply(conversationId, text, (token) => {
        reply += token
        setStreaming(reply)
      })
      setMessages((prior) => [
        ...prior,
        { id: `local-${nextLocalId.current++}`, role: 'ASSISTANT', text: reply.trim(), created_at: '' },
      ])
      setStatus(result.status)
      // An ending moves this exchange into the customer's history.
      if (result.status !== 'ACTIVE') setHistoryKey((n) => n + 1)
      if (result.service_call) {
        // The done frame carries only { id, description } out of ServiceCall's five fields.
        // BookFlow — the sole reader of an escalated call — reads exactly those two, so the cast
        // is safe today; a future BookFlow read of status/customer_id/created_at would see
        // undefined here rather than a compile error.
        onEscalated({
          id: result.service_call.id,
          description: result.service_call.description,
        } as ServiceCall)
      }
    } catch (err) {
      setError(safeErrorMessage(err, 'The assistant could not answer just now. Please try again.'))
      setMessages((prior) => prior.filter((m) => m.id !== optimisticId))
      setDraft(text)
    } finally {
      setStreaming('')
      setSending(false)
    }
  }

  /** Closes the conversation on the customer's say-so, whatever the assistant was in the middle of. */
  async function handleEnd(id: string) {
    setError(null)
    setEnding(true)
    try {
      const conversation = await endConversation(id)
      setStatus(conversation.status)
      setHistoryKey((n) => n + 1)
    } catch (err) {
      setError(safeErrorMessage(err, 'Could not close the chat just now. Please try again.'))
    } finally {
      setEnding(false)
    }
  }

  /** Clears the ended exchange and re-runs the mount effect, which opens a fresh conversation. */
  function startOver() {
    setConversationId(null)
    setMessages([])
    setStreaming('')
    setStatus('ACTIVE')
    setDraft('')
    setError(null)
    setAttempt((n) => n + 1)
  }

  return (
    <div className="chat">
      <h3>Tell us what is wrong</h3>

      {initError && (
        <div className="chat__init-error">
          <p role="alert">{initError}</p>
          <Button type="button" onClick={() => setAttempt((n) => n + 1)}>Try again</Button>
          <Button type="button" variant="secondary" onClick={onGiveUp}>
            Open a service call instead
          </Button>
        </div>
      )}

      {conversationId !== null && (
        <>
          <ErrorBanner message={error} onDismiss={() => setError(null)} />

          {error !== null && (
            <div className="chat__give-up">
              <p>Or skip the questions and describe the problem yourself.</p>
              <Button type="button" variant="secondary" onClick={onGiveUp}>
                Open a service call instead
              </Button>
            </div>
          )}

          {status === 'ACTIVE' ? (
            <>
              <ChatTurns messages={messages}>
                {streaming && (
                  <li className="chat__turn chat__turn--assistant" aria-live="polite">{streaming}</li>
                )}
                <div ref={endRef} />
              </ChatTurns>

              <form onSubmit={handleSend} className="form chat__composer">
                <label>
                  Your message:
                  <textarea
                    value={draft}
                    onChange={(e) => setDraft(e.target.value)}
                    rows={3}
                    required
                    maxLength={MAX_MESSAGE_CHARS}
                    placeholder="Describe the problem…"
                  />
                </label>
                <div className="chat__composer-actions">
                  <Button type="submit" loading={sending} disabled={!draft.trim()}>Send</Button>
                  <Button
                    type="button"
                    variant="secondary"
                    loading={ending}
                    disabled={sending}
                    onClick={() => handleEnd(conversationId)}
                  >
                    End chat
                  </Button>
                </div>
              </form>
            </>
          ) : (
            // An ended exchange is read back from history, not left sitting in the live chat.
            <div className="chat__ended">
              <p>{ENDING_NOTE[status]}</p>
              <Button type="button" variant="secondary" onClick={startOver}>
                Start a new conversation
              </Button>
            </div>
          )}
        </>
      )}

      <PastConversations refreshKey={historyKey} collapseKey={collapseKey} />
    </div>
  )
}
