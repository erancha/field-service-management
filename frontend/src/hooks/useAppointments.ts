import { useState } from 'react'
import type { Appointment } from '../api/types.ts'
import {
  createAppointment,
  rescheduleAppointment,
  cancelAppointment,
  addAppointmentDetails,
} from '../api/scheduling.ts'
import type { CreateAppointmentRequest, RescheduleRequest } from '../api/types.ts'

export interface UseAppointmentsResult {
  appointment: Appointment | null
  loading: boolean
  error: string | null
  book: (data: CreateAppointmentRequest) => Promise<Appointment | null>
  reschedule: (id: string, data: RescheduleRequest) => Promise<void>
  cancel: (id: string) => Promise<void>
  addDetails: (id: string, text: string) => Promise<void>
  clearError: () => void
}

export function useAppointments(): UseAppointmentsResult {
  const [appointment, setAppointment] = useState<Appointment | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  function clearError(): void {
    setError(null)
  }

  async function run<T>(action: () => Promise<T>): Promise<T | undefined> {
    setLoading(true)
    setError(null)
    try {
      return await action()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'An error occurred')
      return undefined
    } finally {
      setLoading(false)
    }
  }

  // Returns the created appointment (or null on failure) so callers can branch on the
  // outcome directly — hook state read after the await is stale render-time closure data.
  async function book(data: CreateAppointmentRequest): Promise<Appointment | null> {
    const result = await run(() => createAppointment(data))
    if (result) setAppointment(result)
    return result ?? null
  }

  async function reschedule(id: string, data: RescheduleRequest): Promise<void> {
    const result = await run(() => rescheduleAppointment(id, data))
    if (result) setAppointment(result)
  }

  async function cancel(id: string): Promise<void> {
    const result = await run(() => cancelAppointment(id))
    if (result) setAppointment(result)
  }

  async function addDetails(id: string, text: string): Promise<void> {
    const result = await run(() => addAppointmentDetails(id, { text }))
    if (result) setAppointment(result)
  }

  return { appointment, loading, error, book, reschedule, cancel, addDetails, clearError }
}
