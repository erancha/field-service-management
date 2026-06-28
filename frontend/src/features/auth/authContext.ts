import { createContext, useContext } from 'react'
import type { CurrentUserResult } from '../../hooks/useCurrentUser.ts'

export const AuthContext = createContext<CurrentUserResult | null>(null)

export function useAuth(): CurrentUserResult {
  const ctx = useContext(AuthContext)
  if (!ctx) throw new Error('useAuth must be used within an AuthProvider')
  return ctx
}
