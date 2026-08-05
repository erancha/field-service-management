import { useEffect, useRef } from 'react'
import type { RefObject } from 'react'

export type EventHandlers = Record<string, (data: unknown) => void>

type Subscriber = {
  handlersRef: RefObject<EventHandlers>
  onOpenRef: RefObject<(() => void) | undefined>
}

/**
 * The page's one SSE connection, shared by every subscribed hook instance.
 *
 * Browsers cap concurrent connections per origin, and each EventSource holds one open for its
 * whole life — so a page whose components each opened their own stream could starve the tab of
 * connections. The first subscriber opens the connection, later ones attach to it, and the last
 * one to leave closes it. Event types are bound lazily as subscribers bring them, and stay bound
 * until the connection closes: a listener for a type nobody currently handles dispatches to no
 * one, which is harmless.
 */
const subscribers = new Set<Subscriber>()
let source: EventSource | null = null
const boundTypes = new Set<string>()

function bindType(type: string): void {
  if (source === null || boundTypes.has(type)) return
  boundTypes.add(type)
  source.addEventListener(type, (event) => {
    let data: unknown
    try {
      data = JSON.parse((event as MessageEvent).data)
    } catch {
      // Ignore malformed payloads rather than crashing the stream consumers.
      return
    }
    for (const subscriber of subscribers) {
      subscriber.handlersRef.current[type]?.(data)
    }
  })
}

function subscribe(subscriber: Subscriber): () => void {
  subscribers.add(subscriber)
  if (source === null) {
    source = new EventSource('/api/events', { withCredentials: true })
    // onopen also fires on the automatic reconnects EventSource performs, letting every
    // subscriber resync state that may have drifted while the stream was down.
    source.onopen = () => {
      for (const s of subscribers) s.onOpenRef.current?.()
    }
  }
  for (const type of Object.keys(subscriber.handlersRef.current)) bindType(type)

  return () => {
    subscribers.delete(subscriber)
    if (subscribers.size === 0 && source !== null) {
      source.close()
      source = null
      boundTypes.clear()
    }
  }
}

/**
 * Subscribe to the server's SSE stream while `enabled`.
 *
 * All hook instances of a page share one EventSource to /api/events (cookies sent automatically
 * same-origin); each named event is dispatched to every subscriber's matching handler. The server
 * only ever sends events for channels the authenticated caller may subscribe to, so a handler set
 * is safe to register regardless of role. Handlers are read through a ref so changing them does
 * not tear down the subscription. `onOpen`, if given, fires on every connect of the shared
 * connection (including reconnects), letting callers resync state that may have drifted while the
 * stream was down; a subscriber joining an already-open connection missed nothing, so it is not
 * called for one.
 */
export function useEventStream(handlers: EventHandlers, enabled = true, onOpen?: () => void): void {
  const handlersRef = useRef(handlers)
  handlersRef.current = handlers
  const onOpenRef = useRef(onOpen)
  onOpenRef.current = onOpen

  useEffect(() => {
    if (!enabled) return
    return subscribe({ handlersRef, onOpenRef })
  }, [enabled])
}
