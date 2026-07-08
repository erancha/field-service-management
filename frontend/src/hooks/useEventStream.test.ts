import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { renderHook, act } from '@testing-library/react'
import { useEventStream } from './useEventStream.ts'
import { FakeEventSource } from '../test/fakeEventSource.ts'

describe('useEventStream', () => {
  beforeEach(() => {
    FakeEventSource.reset()
    vi.stubGlobal('EventSource', FakeEventSource)
  })
  afterEach(() => vi.unstubAllGlobals())

  it('dispatches named events to handlers', () => {
    const onChange = vi.fn()
    renderHook(() => useEventStream({ 'appointment.changed': onChange }))
    act(() => FakeEventSource.last().emit('appointment.changed', { appointment_id: 'a1' }))
    expect(onChange).toHaveBeenCalledWith({ appointment_id: 'a1' })
  })

  it('invokes onOpen on each connect', () => {
    const onOpen = vi.fn()
    renderHook(() => useEventStream({}, true, onOpen))
    act(() => FakeEventSource.last().open())
    expect(onOpen).toHaveBeenCalledTimes(1)
  })
})
