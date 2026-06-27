import { useState, useEffect, useCallback } from 'react'
import type { CurrentUser } from '../api/types.ts'
import { fetchCurrentUser } from '../api/auth.ts'

export type AuthState =
  | { status: 'loading' }
  | { status: 'authenticated'; user: CurrentUser }
  | { status: 'unauthenticated' }

export interface CurrentUserResult {
  auth: AuthState
  refresh: () => void
}

export function useCurrentUser(): CurrentUserResult {
  const [state, setState] = useState<AuthState>({ status: 'loading' })
  const [nonce, setNonce] = useState(0)

  const refresh = useCallback(() => setNonce((n) => n + 1), [])

  useEffect(() => {
    let cancelled = false
    fetchCurrentUser()
      .then((user) => {
        if (cancelled) return
        setState(user ? { status: 'authenticated', user } : { status: 'unauthenticated' })
      })
      .catch(() => {
        if (!cancelled) setState({ status: 'unauthenticated' })
      })
    return () => {
      cancelled = true
    }
  }, [nonce])

  return { auth: state, refresh }
}
