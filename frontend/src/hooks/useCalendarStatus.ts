import { useCallback } from 'react'
import { fetchCalendarStatus } from '../api/calendar.ts'
import { ApiException } from '../api/client.ts'
import { useFetchState } from './useFetchState.ts'

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
  const load = useCallback(
    (): Promise<CalendarConnectionState> =>
      fetchCalendarStatus()
        .then(
          (s): CalendarConnectionState =>
            s.connected
              ? { status: 'connected', fsmCalendarId: s.fsm_calendar_id }
              : { status: 'disconnected' },
        )
        .catch(
          // 401 is the only legal disconnected signal from this endpoint's error path.
          (err): CalendarConnectionState =>
            err instanceof ApiException && err.status === 401
              ? { status: 'disconnected' }
              : { status: 'error' },
        ),
    [],
  )
  const { state, refresh } = useFetchState<CalendarConnectionState>(load, { status: 'loading' })
  return { state, refresh }
}
