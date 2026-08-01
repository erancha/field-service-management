import type { ReactNode } from 'react'
import type { PhotoRef, QuestionSpan, TriageMessage } from '../../api/types.ts'

interface ChatTurnsProps {
  messages: TriageMessage[]
  /** Appended after the stored turns: the live chat adds its streaming bubble and scroll anchor. */
  children?: ReactNode
  /**
   * Renders each turn's photos as thumbnails fetched from this URL instead of a filename chip.
   * Omitted for history read back after the conversation ended, whose photo objects may already
   * be reclaimed, so no fetch is attempted there.
   */
  photoPreviewUrl?: (photo: PhotoRef) => string
  /**
   * Bounds of the question in the final turn, as the backend reported it, emphasised to tie it to
   * the Yes/No buttons below. Null once the offer is spent, and absent for history read back after
   * a conversation ends, so neither emphasises anything.
   */
  questionSpan?: QuestionSpan | null
}

/** The bubbles of a conversation, whether it is the live exchange or one read back from history. */
export function ChatTurns({ messages, children, photoPreviewUrl, questionSpan }: ChatTurnsProps) {
  return (
    <ol className="chat__log">
      {messages.map((message, index) => (
        <li key={message.id} className={`chat__turn chat__turn--${message.role.toLowerCase()}`}>
          {questionSpan && message.role === 'ASSISTANT' && index === messages.length - 1 ? (
            <>
              {message.text.slice(0, questionSpan.start)}
              <strong>{message.text.slice(questionSpan.start, questionSpan.end)}</strong>
              {message.text.slice(questionSpan.end)}
            </>
          ) : (
            message.text
          )}
          {message.photos && message.photos.length > 0 && (
            <ul className="chat__turn-photos">
              {message.photos.map((photo) =>
                photoPreviewUrl ? (
                  <li key={photo.id}>
                    <img
                      className="chat__turn-photo"
                      src={photoPreviewUrl(photo)}
                      alt={photo.filename}
                      loading="lazy"
                    />
                  </li>
                ) : (
                  <li key={photo.id}>📷 {photo.filename}</li>
                ),
              )}
            </ul>
          )}
        </li>
      ))}
      {children}
    </ol>
  )
}
