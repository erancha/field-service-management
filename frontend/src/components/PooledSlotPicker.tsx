import type { PooledSlot } from '../api/types.ts'

function formatSlotTime(slot: PooledSlot): string {
  const start = new Date(slot.start)
  const end = new Date(slot.end)
  return `${start.toLocaleDateString()} ${start.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })} – ${end.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}`
}

// Pooled slots from different technicians can share a start time, so identity is the
// (technician, start) pair — comparing start alone would highlight unrelated slots.
function isSelected(selected: PooledSlot | null, slot: PooledSlot): boolean {
  return (
    selected !== null &&
    selected.technician_id === slot.technician_id &&
    selected.start === slot.start
  )
}

interface PooledSlotPickerProps {
  slots: PooledSlot[]
  selected: PooledSlot | null
  onSelect: (slot: PooledSlot) => void
}

export function PooledSlotPicker({ slots, selected, onSelect }: PooledSlotPickerProps) {
  if (slots.length === 0) {
    return <p className="no-slots">No available slots in the next 7 days.</p>
  }
  return (
    <div className="slot-picker">
      <p className="slot-picker__count">{slots.length} next available slot(s)</p>
      <ul className="slot-picker__list">
        {slots.map((slot) => (
          <li key={`${slot.technician_id}|${slot.start}`}>
            <button
              className={`slot-picker__slot${isSelected(selected, slot) ? ' slot-picker__slot--selected' : ''}`}
              onClick={() => onSelect(slot)}
              type="button"
            >
              <span className="slot-picker__tech">{slot.technician_name}</span>
              <span className="slot-picker__time">{formatSlotTime(slot)}</span>
            </button>
          </li>
        ))}
      </ul>
    </div>
  )
}
