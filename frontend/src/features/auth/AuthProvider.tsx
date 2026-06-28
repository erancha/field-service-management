import type { ReactNode } from 'react'
import { useCurrentUser } from '../../hooks/useCurrentUser.ts'
import { AuthContext } from './authContext.ts'

/**
 * Holds the single source of truth for the current user so any component can re-resolve auth
 * (e.g. after sign-out or a live access decision) without a manual page reload.
 */
export function AuthProvider({ children }: { children: ReactNode }) {
  const value = useCurrentUser()
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}
