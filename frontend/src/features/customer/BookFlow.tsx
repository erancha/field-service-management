import { useEffect, useState } from 'react'
import type { ServiceCall, PooledSlot } from '../../api/types.ts'
import { usePooledAvailability } from '../../hooks/usePooledAvailability.ts'
import { useAppointments } from '../../hooks/useAppointments.ts'
import { PooledSlotPicker } from '../../components/PooledSlotPicker.tsx'
import { Button } from '../../components/Button.tsx'
import { ErrorBanner } from '../../components/ErrorBanner.tsx'
import { AppointmentCard } from '../../components/AppointmentCard.tsx'
import { AddressNudge } from '../profile/AddressNudge.tsx'
import { searchWindow } from '../../utils/slots.ts'

interface BookFlowProps {
  serviceCall: ServiceCall
}

// The customer is offered the soonest slots across the whole technician pool, so the
// only choices are which of those slots to take — no technician id or date range to enter.
const SLOT_COUNT = 5

export function BookFlow({ serviceCall }: BookFlowProps) {
  const [booked, setBooked] = useState(false)
  const [selectedSlot, setSelectedSlot] = useState<PooledSlot | null>(null)

  const availability = usePooledAvailability()
  const appts = useAppointments()

  useEffect(() => {
    void availability.fetch({
      ...searchWindow(),
      limit: SLOT_COUNT,
    })
    // Runs once on mount; availability.fetch resets its own state on each call.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  async function handleBook() {
    if (!selectedSlot) return
    const appointment = await appts.book({
      service_call_id: serviceCall.id,
      technician_id: selectedSlot.technician_id,
      start: selectedSlot.start,
      end: selectedSlot.end,
    })
    if (appointment) setBooked(true)
  }

  if (booked && appts.appointment) {
    return (
      <div className="book-flow">
        <h3>Appointment Booked</h3>
        <ErrorBanner message={appts.error} onDismiss={appts.clearError} />
        <AppointmentCard
          appointment={appts.appointment}
          onReschedule={(id, start, end) => appts.reschedule(id, { start, end })}
          onCancel={appts.cancel}
          onAddDetails={appts.addDetails}
          loading={appts.loading}
        />
      </div>
    )
  }

  return (
    <div className="book-flow">
      <h3>Next Available Slots</h3>
      <AddressNudge />
      <p className="book-flow__sc">Service call: <strong>{serviceCall.description}</strong></p>
      <ErrorBanner message={availability.error} onDismiss={() => availability.reset()} />
      <ErrorBanner message={appts.error} onDismiss={appts.clearError} />
      {availability.loading && <p>Finding the next available slots…</p>}
      <PooledSlotPicker
        slots={availability.slots}
        selected={selectedSlot}
        onSelect={setSelectedSlot}
      />
      <div className="book-flow__actions">
        <Button onClick={handleBook} disabled={!selectedSlot} loading={appts.loading}>
          Book Selected Slot
        </Button>
      </div>
    </div>
  )
}
