import { useCallback, useEffect, useState } from 'react'

export interface FetchStateResult<S> {
  state: S
  refresh: () => void
}

/**
 * Shared skeleton for hooks that load server state on mount and re-load on demand.
 *
 * The previous state is kept while a (re)load is in flight, and a resolution from a
 * superseded load (refresh or unmount) is dropped. `load` must map failures into a state
 * value (e.g. an 'error' variant) inside its promise chain and must be referentially
 * stable across renders — a new identity re-triggers the effect.
 */
export function useFetchState<S>(load: () => Promise<S>, initial: S): FetchStateResult<S> {
  const [state, setState] = useState<S>(initial)
  const [nonce, setNonce] = useState(0)

  const refresh = useCallback(() => setNonce((n) => n + 1), [])

  useEffect(() => {
    let cancelled = false
    load().then((next) => {
      if (!cancelled) setState(next)
    })
    return () => {
      cancelled = true
    }
  }, [nonce, load])

  return { state, refresh }
}
