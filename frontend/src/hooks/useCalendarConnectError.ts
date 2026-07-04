import { useCallback, useEffect, useState } from 'react'
import { useSearchParams } from 'react-router-dom'

/**
 * Surfaces the one-shot `?calendar_connect=denied` flag the backend sets after a failed or declined
 * Google Calendar connect, then strips it from the URL so a reload or bookmark does not resurface the
 * banner. Visibility is held in state, so dismissing hides it until the next rejection.
 */
export function useCalendarConnectError(): { rejected: boolean; dismiss: () => void } {
  const [searchParams, setSearchParams] = useSearchParams()
  const [rejected, setRejected] = useState(() => searchParams.get('calendar_connect') === 'denied')

  useEffect(() => {
    if (searchParams.get('calendar_connect') !== 'denied') return
    setSearchParams(
      (prev) => {
        prev.delete('calendar_connect')
        return prev
      },
      { replace: true },
    )
  }, [searchParams, setSearchParams])

  const dismiss = useCallback(() => setRejected(false), [])
  return { rejected, dismiss }
}
