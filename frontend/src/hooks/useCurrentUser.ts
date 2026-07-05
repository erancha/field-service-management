import { useCallback } from 'react'
import type { CurrentUser } from '../api/types.ts'
import { fetchCurrentUser } from '../api/auth.ts'
import { useFetchState } from './useFetchState.ts'

export type AuthState =
  | { status: 'loading' }
  | { status: 'authenticated'; user: CurrentUser }
  | { status: 'unauthenticated' }
  | { status: 'error' }

export interface CurrentUserResult {
  auth: AuthState
  refresh: () => void
}

export function useCurrentUser(): CurrentUserResult {
  const load = useCallback(
    (): Promise<AuthState> =>
      fetchCurrentUser()
        .then(
          (user): AuthState =>
            user ? { status: 'authenticated', user } : { status: 'unauthenticated' },
        )
        .catch((): AuthState => ({ status: 'error' })),
    [],
  )
  const { state: auth, refresh } = useFetchState<AuthState>(load, { status: 'loading' })
  return { auth, refresh }
}
