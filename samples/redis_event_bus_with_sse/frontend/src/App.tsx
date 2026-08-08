import { useState } from 'react'
import type { FormEvent } from 'react'
import { useEventStream } from '../../../../frontend/src/hooks/useEventStream'

type SampleMessage = { type: string; message: string }

/**
 * Posts messages to backend-2 and lists what comes back over backend-1's SSE stream.
 *
 * Reuses the application's shared-EventSource hook unchanged; every listed entry therefore
 * traveled from the POST through backend-2, Redis, and backend-1's SSE stream before appearing.
 */
export function App() {
  const [draft, setDraft] = useState('')
  const [received, setReceived] = useState<SampleMessage[]>([])

  useEventStream({
    'sample.message': (data) => setReceived((events) => [...events, data as SampleMessage]),
  })

  const post = async (submit: FormEvent) => {
    submit.preventDefault()
    await fetch('/api/publish', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ message: draft }),
    })
    setDraft('')
  }

  return (
    <main style={{ fontFamily: 'sans-serif', maxWidth: '40rem', margin: '2rem auto' }}>
      <h1>Redis event bus + SSE sample</h1>
      <p>
        Each message posts to backend-2, which publishes it on the Redis channel; backend-1 holds
        this page's SSE stream and delivers it back below.
      </p>
      <form onSubmit={post}>
        <input
          value={draft}
          onChange={(change) => setDraft(change.target.value)}
          placeholder="Message to send"
          autoFocus
        />
        <button type="submit">Post</button>
      </form>
      <ol>
        {received.map((event, index) => (
          <li key={index}>{event.message}</li>
        ))}
      </ol>
    </main>
  )
}
