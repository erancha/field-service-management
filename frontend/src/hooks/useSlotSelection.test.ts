import { describe, expect, it, vi } from 'vitest'
import { act, renderHook } from '@testing-library/react'
import { useSlotSelection } from './useSlotSelection.ts'

interface Slot {
  start: string
}

describe('useSlotSelection', () => {
  it('defaults the selection to the first slot once a list arrives', () => {
    const { result, rerender } = renderHook(({ slots }) => useSlotSelection(slots), {
      initialProps: { slots: [] as Slot[] },
    })
    expect(result.current.selected).toBeNull()

    const loaded: Slot[] = [{ start: 'a' }, { start: 'b' }]
    rerender({ slots: loaded })
    expect(result.current.selected).toBe(loaded[0])
  })

  it('keeps a manual selection across renders of the same list, then resets on refetch', () => {
    const first: Slot[] = [{ start: 'a' }, { start: 'b' }]
    const { result, rerender } = renderHook(({ slots }) => useSlotSelection(slots), {
      initialProps: { slots: first },
    })

    act(() => result.current.setSelected(first[1]))
    expect(result.current.selected).toBe(first[1])

    rerender({ slots: first })
    expect(result.current.selected).toBe(first[1])

    const refetched: Slot[] = [{ start: 'c' }]
    rerender({ slots: refetched })
    expect(result.current.selected).toBe(refetched[0])
  })

  it('clears the selection when the list becomes empty', () => {
    const loaded: Slot[] = [{ start: 'a' }]
    const { result, rerender } = renderHook(({ slots }) => useSlotSelection(slots), {
      initialProps: { slots: loaded },
    })
    expect(result.current.selected).toBe(loaded[0])

    rerender({ slots: [] as Slot[] })
    expect(result.current.selected).toBeNull()
  })

  it('moves focus to the first slot control and scrolls it into view when a list arrives', () => {
    const button = document.createElement('button')
    button.scrollIntoView = vi.fn()
    document.body.appendChild(button)

    const { result, rerender } = renderHook(({ slots }) => useSlotSelection(slots), {
      initialProps: { slots: [] as Slot[] },
    })
    result.current.firstSlotRef.current = button

    rerender({ slots: [{ start: 'a' }] })
    expect(button).toHaveFocus()
    expect(button.scrollIntoView).toHaveBeenCalledWith({ block: 'center' })

    button.remove()
  })
})
