import type { CurrentUser } from '../../api/types.ts'

const SKIP_KEY_PREFIX = 'fsm-onboarding-skipped:'

// Session-scoped by design: a skip lasts until the browser session ends, so the prompt
// returns on the next visit until the profile is complete.
export function needsOnboarding(user: CurrentUser): boolean {
  return (
    user.role === 'CUSTOMER' &&
    user.role_status === 'APPROVED' &&
    (!user.address || !user.phone)
  )
}

export function hasSkippedOnboarding(userId: string): boolean {
  return sessionStorage.getItem(SKIP_KEY_PREFIX + userId) === '1'
}

export function markOnboardingSkipped(userId: string): void {
  sessionStorage.setItem(SKIP_KEY_PREFIX + userId, '1')
}
