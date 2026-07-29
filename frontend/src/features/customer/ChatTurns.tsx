import type { ReactNode } from 'react'
import type { TriageMessage } from '../../api/types.ts'

interface ChatTurnsProps {
  messages: TriageMessage[]
  /** Appended after the stored turns: the live chat adds its streaming bubble and scroll anchor. */
  children?: ReactNode
}

/** The bubbles of a conversation, whether it is the live exchange or one read back from history. */
export function ChatTurns({ messages, children }: ChatTurnsProps) {
  return (
    <ol className="chat__log">
      {messages.map((message) => (
        <li key={message.id} className={`chat__turn chat__turn--${message.role.toLowerCase()}`}>
          {message.text}
        </li>
      ))}
      {children}
    </ol>
  )
}
