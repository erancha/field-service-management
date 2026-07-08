import { useEffect } from 'react'
import type { ServiceCall, PooledSlot } from '../../api/types.ts'
import { usePooledAvailability } from '../../hooks/useAvailability.ts'
import { useSlotSelection } from '../../hooks/useSlotSelection.ts'
import { useAppointments } from '../../hooks/useAppointments.ts'
import { PooledSlotPicker } from '../../components/PooledSlotPicker.tsx'
import { Button } from '../../components/Button.tsx'
import { ErrorBanner } from '../../components/ErrorBanner.tsx'
import { AddressNudge } from '../profile/AddressNudge.tsx'
import { searchWindow } from '../../utils/slots.ts'

interface BookFlowProps {
  serviceCall: ServiceCall
  onBooked: () => void
}

// The customer is offered the soonest slots across the whole technician pool, so the
// only choices are which of those slots to take — no technician id or date range to enter.
const SLOT_COUNT = 5

export function BookFlow({ serviceCall, onBooked }: BookFlowProps) {
  const availability = usePooledAvailability()
  const appts = useAppointments()
  const { selected: selectedSlot, setSelected: setSelectedSlot, firstSlotRef } =
    useSlotSelection<PooledSlot>(availability.slots)

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
    // The booked appointment surfaces through the dashboard's upcoming list; booking hands control
    // back to the page, which owns what the customer sees next.
    if (appointment) onBooked()
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
        firstSlotRef={firstSlotRef}
      />
      <div className="book-flow__actions">
        <Button onClick={handleBook} disabled={!selectedSlot} loading={appts.loading}>
          Book Selected Slot
        </Button>
      </div>
    </div>
  )
}
