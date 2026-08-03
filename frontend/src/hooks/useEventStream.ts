import { useEffect, useRef } from 'react'

export type EventHandlers = Record<string, (data: unknown) => void>

/**
 * Subscribe to the server's SSE stream while `enabled`.
 *
 * Opens a single EventSource to /api/events (cookies sent automatically same-origin) and dispatches
 * each named event to the matching handler. The server only ever sends events for channels the
 * authenticated caller may subscribe to, so a handler set is safe to register regardless of role.
 * Handlers are read through a ref so changing them does not tear down and reopen the connection.
 * `onOpen`, if given, fires on every connect (including reconnects), letting callers resync state
 * that may have drifted while the stream was down.
 */
export function useEventStream(handlers: EventHandlers, enabled = true, onOpen?: () => void): void {
  const handlersRef = useRef(handlers)
  handlersRef.current = handlers
  const onOpenRef = useRef(onOpen)
  onOpenRef.current = onOpen

  useEffect(() => {
    if (!enabled) return
    const source = new EventSource('/api/events', { withCredentials: true })
    source.onopen = () => onOpenRef.current?.()
    const types = Object.keys(handlersRef.current)

    const listeners = types.map((type) => {
      const listener = (event: MessageEvent) => {
        const handler = handlersRef.current[type]
        if (!handler) return
        try {
          handler(JSON.parse(event.data))
        } catch {
          // Ignore malformed payloads rather than crashing the stream consumer.
        }
      }
      source.addEventListener(type, listener as EventListener)
      return { type, listener }
    })

    return () => {
      for (const { type, listener } of listeners) {
        source.removeEventListener(type, listener as EventListener)
      }
      source.close()
    }
  }, [enabled])
}
