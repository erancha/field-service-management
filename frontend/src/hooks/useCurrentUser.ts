import { useState, useEffect } from 'react'
import type { CurrentUser } from '../api/types.ts'
import { fetchCurrentUser } from '../api/auth.ts'

export type AuthState =
  | { status: 'loading' }
  | { status: 'authenticated'; user: CurrentUser }
  | { status: 'unauthenticated' }
  | { status: 'unavailable' }

export function useCurrentUser(): AuthState {
  const [state, setState] = useState<AuthState>({ status: 'loading' })

  useEffect(() => {
    let cancelled = false
    fetchCurrentUser()
      .then((user) => {
        if (cancelled) return
        if (user) {
          setState({ status: 'authenticated', user })
        } else {
          setState({ status: 'unauthenticated' })
        }
      })
      .catch(() => {
        if (!cancelled) setState({ status: 'unavailable' })
      })
    return () => {
      cancelled = true
    }
  }, [])

  return state
}
