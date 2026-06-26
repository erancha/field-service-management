import type { TimeSlot } from '../api/types.ts'

function formatSlot(slot: TimeSlot): string {
  const start = new Date(slot.start)
  const end = new Date(slot.end)
  return `${start.toLocaleDateString()} ${start.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })} – ${end.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}`
}

interface SlotPickerProps {
  slots: TimeSlot[]
  selected: TimeSlot | null
  onSelect: (slot: TimeSlot) => void
}

export function SlotPicker({ slots, selected, onSelect }: SlotPickerProps) {
  if (slots.length === 0) {
    return <p className="no-slots">No available slots found for the selected period.</p>
  }
  return (
    <div className="slot-picker">
      <p className="slot-picker__count">{slots.length} slot(s) available</p>
      <ul className="slot-picker__list">
        {slots.map((slot, i) => (
          <li key={i}>
            <button
              className={`slot-picker__slot${selected?.start === slot.start ? ' slot-picker__slot--selected' : ''}`}
              onClick={() => onSelect(slot)}
              type="button"
            >
              {formatSlot(slot)}
            </button>
          </li>
        ))}
      </ul>
    </div>
  )
}
