import { useEffect } from 'react'
import type { TimeSlot } from '../api/types.ts'
import { useAvailability } from '../hooks/useAvailability.ts'
import { useSlotSelection } from '../hooks/useSlotSelection.ts'
import { formatSlotRange, searchWindow, SEARCH_DAYS } from '../utils/slots.ts'
import { Button } from './Button.tsx'

interface ReschedulePickerProps {
  technicianId: string
  onConfirm: (start: string, end: string) => void
  loading?: boolean
}

// Reschedule keeps the appointment's technician, so the offered slots come from that
// technician's own availability rather than the whole pool used at booking time.
export function ReschedulePicker({ technicianId, onConfirm, loading = false }: ReschedulePickerProps) {
  const availability = useAvailability()
  const { selected, setSelected, firstSlotRef } = useSlotSelection<TimeSlot>(availability.slots)

  useEffect(() => {
    void availability.fetch({ technician_id: technicianId, ...searchWindow() })
    // Runs once per technician; availability.fetch resets its own state on each call.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [technicianId])

  if (availability.loading) {
    return <p className="slot-picker__loading">Loading available slots…</p>
  }
  if (availability.error) {
    return <p className="error">{availability.error}</p>
  }
  if (availability.slots.length === 0) {
    return <p className="no-slots">No available slots in the next {SEARCH_DAYS} days.</p>
  }

  return (
    <div className="appointment-card__reschedule slot-picker">
      <ul className="slot-picker__list">
        {availability.slots.map((slot, index) => (
          <li key={slot.start}>
            <button
              ref={index === 0 ? firstSlotRef : null}
              className={`slot-picker__slot${selected?.start === slot.start ? ' slot-picker__slot--selected' : ''}`}
              onClick={() => setSelected(slot)}
              type="button"
            >
              <span className="slot-picker__time">{formatSlotRange(slot.start, slot.end)}</span>
            </button>
          </li>
        ))}
      </ul>
      <Button
        onClick={() => selected && onConfirm(selected.start, selected.end)}
        disabled={!selected}
        loading={loading}
      >
        Confirm
      </Button>
    </div>
  )
}
