import { useState, useEffect, useCallback } from 'react'
import { fetchCalendarStatus } from '../api/calendar.ts'
import { ApiException } from '../api/client.ts'

export type CalendarConnectionState =
  | { status: 'loading' }
  | { status: 'connected'; fsmCalendarId: string | null }
  | { status: 'disconnected' }
  | { status: 'error' }

export interface CalendarStatusResult {
  state: CalendarConnectionState
  refresh: () => void
}

export function useCalendarStatus(): CalendarStatusResult {
  const [state, setState] = useState<CalendarConnectionState>({ status: 'loading' })
  const [nonce, setNonce] = useState(0)

  const refresh = useCallback(() => setNonce((n) => n + 1), [])

  useEffect(() => {
    let cancelled = false
    fetchCalendarStatus()
      .then((s) => {
        if (cancelled) return
        setState(
          s.connected
            ? { status: 'connected', fsmCalendarId: s.fsm_calendar_id }
            : { status: 'disconnected' },
        )
      })
      .catch((err) => {
        if (cancelled) return
        // 401 is the only legal disconnected signal from this endpoint's error path.
        setState(err instanceof ApiException && err.status === 401
          ? { status: 'disconnected' }
          : { status: 'error' })
      })
    return () => {
      cancelled = true
    }
  }, [nonce])

  return { state, refresh }
}
