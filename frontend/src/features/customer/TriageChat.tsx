import { useEffect, useRef, useState } from 'react'
import { ApiException } from '../../api/client.ts'
import {
  deleteTriagePhoto,
  endConversation,
  startConversation,
  streamAssistReply,
  triagePhotoPreviewUrl,
  uploadTriagePhoto,
} from '../../api/assist.ts'
import type {
  PhotoRef,
  QuestionSpan,
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
const MAX_PHOTOS = 5
const MAX_PHOTO_MB = 5
const MAX_PHOTO_BYTES = MAX_PHOTO_MB * 1024 * 1024
const PHOTO_TYPES = ['image/jpeg', 'image/png', 'image/webp']

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
  const [questionSpan, setQuestionSpan] = useState<QuestionSpan | null>(null)
  const [sending, setSending] = useState(false)
  const [ending, setEnding] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [initError, setInitError] = useState<string | null>(null)
  const [attempt, setAttempt] = useState(0)
  const [historyKey, setHistoryKey] = useState(0)
  const [collapseKey, setCollapseKey] = useState(0)
  const [pendingPhotos, setPendingPhotos] = useState<PhotoRef[]>([])
  const [uploadingPhoto, setUploadingPhoto] = useState(false)
  const [sendOnTap, setSendOnTap] = useState(true)
  const [attachOpen, setAttachOpen] = useState(false)
  const [caretToEnd, setCaretToEnd] = useState(0)
  const endRef = useRef<HTMLDivElement>(null)
  const draftRef = useRef<HTMLTextAreaElement>(null)
  const nextLocalId = useRef(0)
  const attachedCount =
    messages.reduce((n, m) => n + (m.photos?.length ?? 0), 0) + pendingPhotos.length

  useEffect(() => {
    let cancelled = false
    setInitError(null)
    startConversation()
      .then((conversation) => {
        if (cancelled) return
        setConversationId(conversation.id)
        setMessages(conversation.messages)
        setStatus(conversation.status)
        setPendingPhotos(conversation.pending_photos)
      })
      .catch((err) => {
        if (!cancelled) setInitError(safeErrorMessage(err, 'Could not reach the assistant'))
      })
    return () => { cancelled = true }
  }, [attempt])

  useEffect(() => { endRef.current?.scrollIntoView({ block: 'end' }) }, [messages, streaming])

  // Focus belongs in the composer, and both dependencies are a moment it has to be put back: the
  // composer mounts only once the conversation resolves, and clicking Send moves focus to Send.
  useEffect(() => { if (!sending) draftRef.current?.focus() }, [conversationId, sending])

  // A quick reply diverted into the composer arrives as a prefix, so the caret belongs at its end.
  // This runs after the commit that applied that draft, which is when the caret can be placed.
  useEffect(() => {
    if (caretToEnd === 0) return
    const composer = draftRef.current
    if (composer === null) return
    composer.focus()
    composer.setSelectionRange(composer.value.length, composer.value.length)
  }, [caretToEnd])

  /**
   * A tapped Yes/No sends the answer as its own turn, which is the point of the buttons: most
   * yes/no questions need nothing more. Anything already typed is carried into the answer —
   * "No, only the mast one is lit" — so a tap never strands the customer's own words.
   *
   * Clearing "Send" first diverts the answer into the composer unsent, for the question where yes
   * or no is only the opening of the reply.
   *
   * The offer is spent on the first tap either way: the answer is now a turn or editable text, and
   * a second tap would stack a second prefix onto it.
   */
  function handleQuickReply(answer: 'Yes' | 'No') {
    const typed = draft.trim()
    const answered = typed ? `${answer}, ${typed}` : answer
    setQuestionSpan(null)
    if (sendOnTap) {
      void send(answered)
      return
    }
    setDraft(answered)
    setCaretToEnd((n) => n + 1)
  }

  async function handleSend(e: React.FormEvent) {
    e.preventDefault()
    await send(draft.trim())
  }

  async function send(text: string) {
    if (conversationId === null) return
    const sent = pendingPhotos
    setError(null)
    setDraft('')
    // Whatever the previous turn asked has now been answered, however the customer chose to.
    setQuestionSpan(null)
    setSending(true)
    // The live exchange is what the customer is now watching; history folds out of its way.
    setCollapseKey((n) => n + 1)
    const optimisticId = `local-${nextLocalId.current++}`
    setMessages((prior) => [
      ...prior,
      { id: optimisticId, role: 'CUSTOMER', text, created_at: '', photos: sent },
    ])

    let reply = ''
    try {
      const result = await streamAssistReply(
        conversationId,
        text,
        sent.map((photo) => photo.id),
        (token) => {
          reply += token
          setStreaming(reply)
        },
      )
      setMessages((prior) => [
        ...prior,
        { id: `local-${nextLocalId.current++}`, role: 'ASSISTANT', text: reply.trim(), created_at: '' },
      ])
      setStatus(result.status)
      setQuestionSpan(result.question)
      setPendingPhotos([])
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
      // The ids stay unbound server-side, so a retried turn can re-send the same photos.
    } finally {
      setStreaming('')
      setSending(false)
    }
  }

  async function handleAttach(e: React.ChangeEvent<HTMLInputElement>) {
    const files = Array.from(e.target.files ?? [])
    e.target.value = ''
    if (conversationId === null || files.length === 0) return
    setError(null)
    if (attachedCount + files.length > MAX_PHOTOS) {
      setError(`A conversation can carry at most ${MAX_PHOTOS} photos.`)
      return
    }
    for (const file of files) {
      if (!PHOTO_TYPES.includes(file.type)) {
        setError('Photos must be JPEG, PNG, or WebP images.')
        return
      }
      if (file.size > MAX_PHOTO_BYTES) {
        setError(`Each photo must be ${MAX_PHOTO_MB} MB or less.`)
        return
      }
    }
    setUploadingPhoto(true)
    try {
      for (const file of files) {
        const photo = await uploadTriagePhoto(conversationId, file)
        setPendingPhotos((prior) => [...prior, photo])
      }
    } catch (err) {
      setError(safeErrorMessage(err, 'The photo could not be uploaded. Please try again.'))
    } finally {
      setUploadingPhoto(false)
    }
  }

  async function handleRemovePhoto(photoId: string) {
    if (conversationId === null) return
    try {
      await deleteTriagePhoto(conversationId, photoId)
      setPendingPhotos((prior) => prior.filter((photo) => photo.id !== photoId))
    } catch (err) {
      setError(safeErrorMessage(err, 'The photo could not be removed. Please try again.'))
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
    setPendingPhotos([])
    setConversationId(null)
    setMessages([])
    setStreaming('')
    setStatus('ACTIVE')
    setDraft('')
    setQuestionSpan(null)
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
              <ChatTurns
                messages={messages}
                photoPreviewUrl={(photo) => triagePhotoPreviewUrl(conversationId, photo.id)}
                questionSpan={questionSpan}
              >
                {streaming && (
                  <li className="chat__turn chat__turn--assistant" aria-live="polite">{streaming}</li>
                )}
                <div ref={endRef} />
              </ChatTurns>

              {questionSpan && (
                <div className="chat__quick-replies">
                  <Button
                    type="button"
                    variant="success"
                    disabled={sending}
                    onClick={() => handleQuickReply('Yes')}
                  >
                    Yes
                  </Button>
                  <Button
                    type="button"
                    variant="danger"
                    disabled={sending}
                    onClick={() => handleQuickReply('No')}
                  >
                    No
                  </Button>
                  <label className="chat__quick-reply-send">
                    <input
                      type="checkbox"
                      checked={sendOnTap}
                      onChange={(e) => setSendOnTap(e.target.checked)}
                      disabled={sending}
                    />
                    Send
                  </label>
                </div>
              )}

              <form onSubmit={handleSend} className="form chat__composer">
                <div className="chat__composer-field">
                  <div className="chat__composer-head">
                    <label htmlFor="chat-draft">Your message:</label>
                    <button
                      type="button"
                      className="chat__attach-toggle"
                      aria-expanded={attachOpen}
                      aria-controls="chat-attach"
                      onClick={() => setAttachOpen((open) => !open)}
                    >
                      <span aria-hidden="true">+</span>
                      Attach photos
                    </button>
                  </div>
                  <textarea
                    id="chat-draft"
                    ref={draftRef}
                    value={draft}
                    onChange={(e) => setDraft(e.target.value)}
                    rows={3}
                    maxLength={MAX_MESSAGE_CHARS}
                    placeholder="Describe the problem…"
                  />
                </div>
                {(pendingPhotos.length > 0 || uploadingPhoto) && (
                  <p className="chat__attach-note">
                    {uploadingPhoto
                      ? 'Uploading photo…'
                      : 'Attached — will be sent with your next message.'}
                  </p>
                )}
                {pendingPhotos.length > 0 && (
                  <ul className="chat__photo-strip">
                    {pendingPhotos.map((photo) => (
                      <li key={photo.id}>
                        <img
                          src={triagePhotoPreviewUrl(conversationId, photo.id)}
                          alt={photo.filename}
                        />
                        <button
                          type="button"
                          aria-label={`Remove ${photo.filename}`}
                          onClick={() => handleRemovePhoto(photo.id)}
                        >
                          ×
                        </button>
                      </li>
                    ))}
                  </ul>
                )}
                {attachOpen && (
                  <label className="chat__attach" id="chat-attach">
                    Attach photos
                    <input
                      type="file"
                      accept="image/jpeg,image/png,image/webp"
                      multiple
                      onChange={handleAttach}
                      disabled={sending || uploadingPhoto || attachedCount >= MAX_PHOTOS}
                    />
                  </label>
                )}
                <div className="chat__composer-actions">
                  <Button
                    type="submit"
                    loading={sending}
                    disabled={!draft.trim() && pendingPhotos.length === 0}
                  >
                    Send
                  </Button>
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
