import { describe, expect, it } from 'vitest'
import { act, renderHook, waitFor } from '@testing-library/react'
import { useFetchState } from './useFetchState.ts'

describe('useFetchState', () => {
  it('holds the initial state until load resolves, then stores the loaded state', async () => {
    let resolve!: (value: string) => void
    const load = () => new Promise<string>((r) => { resolve = r })

    const { result } = renderHook(() => useFetchState(load, 'initial'))

    expect(result.current.state).toBe('initial')
    resolve('loaded')
    await waitFor(() => expect(result.current.state).toBe('loaded'))
  })

  it('re-runs load on refresh', async () => {
    let calls = 0
    const load = () => Promise.resolve(`load-${++calls}`)

    const { result } = renderHook(() => useFetchState(load, 'initial'))
    await waitFor(() => expect(result.current.state).toBe('load-1'))

    act(() => result.current.refresh())
    await waitFor(() => expect(result.current.state).toBe('load-2'))
  })

  it('drops a resolution from a load superseded by refresh', async () => {
    const resolvers: Array<(value: string) => void> = []
    const load = () => new Promise<string>((r) => { resolvers.push(r) })

    const { result } = renderHook(() => useFetchState(load, 'initial'))
    act(() => result.current.refresh())
    await waitFor(() => expect(resolvers).toHaveLength(2))

    resolvers[1]('second')
    await waitFor(() => expect(result.current.state).toBe('second'))

    resolvers[0]('first')
    await act(async () => {})
    expect(result.current.state).toBe('second')
  })
})
