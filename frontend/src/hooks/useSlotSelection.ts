import { useEffect, useRef, useState, type RefObject } from 'react'

export interface SlotSelection<Slot, El extends HTMLElement> {
  selected: Slot | null
  setSelected: (slot: Slot) => void
  firstSlotRef: RefObject<El | null>
}

/**
 * Tracks which slot the user has chosen from a fetched availability list, keeping the highlight
 * and keyboard focus in sync with the common case.
 *
 * The soonest slot is the common choice, so whenever a new list arrives the first slot is both
 * selected and focused (attach firstSlotRef to its control), making the happy path a single
 * confirm click with Tab/arrows reaching the rest. The array identity only changes on a fetch, so
 * a manual pick survives re-renders of the same list and resets on refetch; an empty list clears
 * the selection.
 */
export function useSlotSelection<Slot, El extends HTMLElement = HTMLButtonElement>(
  slots: Slot[],
): SlotSelection<Slot, El> {
  const [selected, setSelected] = useState<Slot | null>(null)
  const firstSlotRef = useRef<El | null>(null)

  useEffect(() => {
    setSelected(slots.length > 0 ? slots[0] : null)
    if (slots.length > 0) {
      firstSlotRef.current?.focus()
      // focus() alone only guarantees minimal visibility; centering the row makes the
      // focused slot unmistakable even when the picker sits below the fold.
      firstSlotRef.current?.scrollIntoView({ block: 'center' })
    }
  }, [slots])

  return { selected, setSelected, firstSlotRef }
}
