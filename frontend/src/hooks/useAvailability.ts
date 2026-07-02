import { useState } from 'react'
import type { TimeSlot } from '../api/types.ts'
import { fetchAvailability, type AvailabilityParams } from '../api/scheduling.ts'

export interface UseAvailabilityResult {
  slots: TimeSlot[]
  loading: boolean
  error: string | null
  fetch: (params: AvailabilityParams) => Promise<void>
}

export function useAvailability(): UseAvailabilityResult {
  const [slots, setSlots] = useState<TimeSlot[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function fetch(params: AvailabilityParams): Promise<void> {
    setLoading(true)
    setError(null)
    setSlots([])
    try {
      const result = await fetchAvailability(params)
      setSlots(result.slots)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to fetch availability')
    } finally {
      setLoading(false)
    }
  }

  return { slots, loading, error, fetch }
}
