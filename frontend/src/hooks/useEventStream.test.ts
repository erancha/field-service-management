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

  it('shares one connection across concurrent subscribers', () => {
    renderHook(() => useEventStream({ 'a.changed': vi.fn() }))
    renderHook(() => useEventStream({ 'b.changed': vi.fn() }))
    expect(FakeEventSource.instances).toHaveLength(1)
  })

  it('dispatches an event to every subscriber handling its type', () => {
    const first = vi.fn()
    const second = vi.fn()
    renderHook(() => useEventStream({ 'appointment.changed': first }))
    renderHook(() => useEventStream({ 'appointment.changed': second }))
    act(() => FakeEventSource.last().emit('appointment.changed', { appointment_id: 'a1' }))
    expect(first).toHaveBeenCalledWith({ appointment_id: 'a1' })
    expect(second).toHaveBeenCalledWith({ appointment_id: 'a1' })
  })

  it('binds a late subscriber\'s event types to the existing connection', () => {
    const late = vi.fn()
    renderHook(() => useEventStream({ 'a.changed': vi.fn() }))
    renderHook(() => useEventStream({ 'b.changed': late }))
    act(() => FakeEventSource.last().emit('b.changed', { ok: true }))
    expect(late).toHaveBeenCalledWith({ ok: true })
  })

  it('keeps the connection until the last subscriber unmounts', () => {
    const first = renderHook(() => useEventStream({ 'a.changed': vi.fn() }))
    const second = renderHook(() => useEventStream({ 'b.changed': vi.fn() }))
    const source = FakeEventSource.last()

    first.unmount()
    expect(source.closed).toBe(false)

    second.unmount()
    expect(source.closed).toBe(true)
  })

  it('fans onOpen out to every subscriber', () => {
    const first = vi.fn()
    const second = vi.fn()
    renderHook(() => useEventStream({}, true, first))
    renderHook(() => useEventStream({}, true, second))
    act(() => FakeEventSource.last().open())
    expect(first).toHaveBeenCalledTimes(1)
    expect(second).toHaveBeenCalledTimes(1)
  })

  it('opens nothing while no subscriber is enabled', () => {
    renderHook(() => useEventStream({ 'a.changed': vi.fn() }, false))
    expect(FakeEventSource.instances).toHaveLength(0)
  })
})
