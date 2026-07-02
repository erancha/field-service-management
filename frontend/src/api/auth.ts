import type { CurrentUser, ProfileUpdate } from './types.ts'
import { apiFetch, apiPatch } from './client.ts'

export async function fetchCurrentUser(): Promise<CurrentUser | null> {
  try {
    return await apiFetch<CurrentUser>('/auth/me')
  } catch {
    return null
  }
}

export async function updateProfile(patch: ProfileUpdate): Promise<CurrentUser> {
  return apiPatch<CurrentUser>('/auth/me', patch)
}

export async function logout(): Promise<void> {
  await apiFetch('/auth/logout', { method: 'POST' })
}

export function getGoogleLoginUrl(): string {
  return '/auth/google/login'
}
