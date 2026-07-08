import { useCallback, useEffect, useRef, useState } from 'react'
import type { UpcomingAppointment } from '../api/types.ts'
import { fetchUpcomingAppointments } from '../api/scheduling.ts'
import { useEventStream } from './useEventStream.ts'
import { errorMessage } from '../utils/errors.ts'

export interface UpcomingAppointmentsResult {
  items: UpcomingAppointment[]
  loading: boolean
  error: string | null
  refetch: () => Promise<void>
}

/**
 * Load and live-maintain the caller's upcoming appointments.
 *
 * Fetches once on mount, then refetches whenever an appointment.changed event arrives or the SSE
 * stream reconnects (so a change missed while disconnected is picked up). The server scopes the
 * result to the authenticated role, so the same hook serves every dashboard.
 */
export function useUpcomingAppointments(limit: number): UpcomingAppointmentsResult {
  const [items, setItems] = useState<UpcomingAppointment[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const firstOpen = useRef(true)

  const refetch = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const result = await fetchUpcomingAppointments({ limit })
      setItems(result.items)
    } catch (err) {
      setError(errorMessage(err, 'Failed to load appointments'))
    } finally {
      setLoading(false)
    }
  }, [limit])

  useEffect(() => {
    void refetch()
  }, [refetch])

  useEventStream(
    { 'appointment.changed': () => void refetch() },
    true,
    () => {
      // The initial connect already ran the mount fetch; only reconnects need a catch-up refetch.
      if (firstOpen.current) {
        firstOpen.current = false
        return
      }
      void refetch()
    },
  )

  return { items, loading, error, refetch }
}
