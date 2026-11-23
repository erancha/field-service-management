import type { CurrentUser, ProfileUpdate } from './types.ts'
import { apiFetch, apiPatch, ApiException } from './client.ts'

export async function fetchCurrentUser(): Promise<CurrentUser | null> {
  try {
    return await apiFetch<CurrentUser>('/auth/me')
  } catch (err) {
    if (err instanceof ApiException && err.status === 401) return null
    throw err
  }
}

export async function updateProfile(patch: ProfileUpdate): Promise<CurrentUser> {
  return apiPatch<CurrentUser>('/auth/me', patch)
}

export async function acceptAssistDisclaimer(): Promise<CurrentUser> {
  return apiFetch<CurrentUser>('/auth/me/assist-disclaimer', { method: 'POST' })
}

export async function logout(): Promise<void> {
  await apiFetch('/auth/logout', { method: 'POST' })
}

/** Leaves for the backend's Google sign-in, which returns to this role's app when it completes. */
export function startGoogleSignIn(): void {
  window.location.assign('/auth/google/login')
}
