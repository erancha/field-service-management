import { useState } from 'react'
import type { PooledSlot, TimeSlot } from '../api/types.ts'
import {
  fetchAvailability,
  fetchPooledAvailability,
  type AvailabilityParams,
  type PooledAvailabilityParams,
} from '../api/scheduling.ts'
import { errorMessage } from '../utils/errors.ts'

export interface SlotsFetchResult<Slot, Params> {
  slots: Slot[]
  loading: boolean
  error: string | null
  fetch: (params: Params) => Promise<void>
  reset: () => void
}

export type UseAvailabilityResult = SlotsFetchResult<TimeSlot, AvailabilityParams>
export type UsePooledAvailabilityResult = SlotsFetchResult<PooledSlot, PooledAvailabilityParams>

/**
 * On-demand availability lookup: fetch(params) replaces the slot list, surfacing failures
 * as a display message; reset returns to the idle empty state.
 */
function useSlotsFetch<Slot, Params>(
  fetchSlots: (params: Params) => Promise<{ slots: Slot[] }>,
): SlotsFetchResult<Slot, Params> {
  const [slots, setSlots] = useState<Slot[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function fetch(params: Params): Promise<void> {
    setLoading(true)
    setError(null)
    setSlots([])
    try {
      const result = await fetchSlots(params)
      setSlots(result.slots)
    } catch (err) {
      setError(errorMessage(err, 'Failed to fetch availability'))
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

export function useAvailability(): UseAvailabilityResult {
  return useSlotsFetch(fetchAvailability)
}

export function usePooledAvailability(): UsePooledAvailabilityResult {
  return useSlotsFetch(fetchPooledAvailability)
}
