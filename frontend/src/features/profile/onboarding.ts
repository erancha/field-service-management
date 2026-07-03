import type { CurrentUser } from '../../api/types.ts'

const SKIP_KEY_PREFIX = 'fsm-onboarding-skipped:'

// Session-scoped by design: a skip lasts until the browser session ends, so the prompt
// returns on the next visit until the profile is complete.
//
// A customer must supply an address and phone before booking; a technician must supply a phone so
// the customer can reach them (their address is collected for dispatch but not required to book).
export function needsOnboarding(user: CurrentUser): boolean {
  if (user.role_status !== 'APPROVED') return false
  if (user.role === 'CUSTOMER') return !user.address?.trim() || !user.phone?.trim()
  if (user.role === 'TECHNICIAN') return !user.phone?.trim()
  return false
}

export function hasSkippedOnboarding(userId: string): boolean {
  return sessionStorage.getItem(SKIP_KEY_PREFIX + userId) === '1'
}

export function markOnboardingSkipped(userId: string): void {
  sessionStorage.setItem(SKIP_KEY_PREFIX + userId, '1')
}
