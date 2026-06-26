import type { CurrentUser } from './types.ts'
import { apiFetch } from './client.ts'

export async function fetchCurrentUser(): Promise<CurrentUser | null> {
  try {
    return await apiFetch<CurrentUser>('/auth/me')
  } catch {
    return null
  }
}

export async function logout(): Promise<void> {
  await apiFetch('/auth/logout', { method: 'POST' })
}

export function getGoogleLoginUrl(): string {
  return '/auth/google/login'
}
