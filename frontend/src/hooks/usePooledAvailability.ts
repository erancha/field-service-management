import { useState } from 'react'
import type { PooledSlot } from '../api/types.ts'
import { fetchPooledAvailability, type PooledAvailabilityParams } from '../api/scheduling.ts'

export interface UsePooledAvailabilityResult {
  slots: PooledSlot[]
  loading: boolean
  error: string | null
  fetch: (params: PooledAvailabilityParams) => Promise<void>
  reset: () => void
}

export function usePooledAvailability(): UsePooledAvailabilityResult {
  const [slots, setSlots] = useState<PooledSlot[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function fetch(params: PooledAvailabilityParams): Promise<void> {
    setLoading(true)
    setError(null)
    setSlots([])
    try {
      const result = await fetchPooledAvailability(params)
      setSlots(result.slots)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to fetch availability')
    } finally {
      setLoading(false)
    }
  }

  function reset(): void {
    setSlots([])
    setError(null)
    setLoading(false)
  }

  return { slots, loading, error, fetch, reset }
}
