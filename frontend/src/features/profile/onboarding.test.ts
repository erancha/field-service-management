import { beforeEach, describe, expect, it } from 'vitest'
import { hasSkippedOnboarding, markOnboardingSkipped, needsOnboarding } from './onboarding.ts'
import type { CurrentUser } from '../../api/types.ts'

function user(overrides: Partial<CurrentUser> = {}): CurrentUser {
  return {
    user_id: 'u-1',
    email: 'c@example.com',
    role: 'CUSTOMER',
    role_status: 'APPROVED',
    name: 'Google Name',
    display_name: null,
    address: null,
    phone: null,
    ...overrides,
  }
}

beforeEach(() => sessionStorage.clear())

describe('needsOnboarding', () => {
  it('is true for a customer missing address or phone', () => {
    expect(needsOnboarding(user())).toBe(true)
    expect(needsOnboarding(user({ address: '12 Main St' }))).toBe(true)
    expect(needsOnboarding(user({ phone: '+972-50' }))).toBe(true)
  })

  it('is false once both address and phone are set', () => {
    expect(needsOnboarding(user({ address: '12 Main St', phone: '+972-50' }))).toBe(false)
  })

  it('is false for non-customers', () => {
    expect(needsOnboarding(user({ role: 'TECHNICIAN' }))).toBe(false)
    expect(needsOnboarding(user({ role: 'ADMIN' }))).toBe(false)
  })

  it('is false for a customer not yet approved', () => {
    expect(needsOnboarding(user({ role_status: 'PENDING' }))).toBe(false)
    expect(needsOnboarding(user({ role_status: 'REJECTED' }))).toBe(false)
  })
})

describe('skip flag', () => {
  it('round-trips per user id in sessionStorage', () => {
    expect(hasSkippedOnboarding('u-1')).toBe(false)
    markOnboardingSkipped('u-1')
    expect(hasSkippedOnboarding('u-1')).toBe(true)
    expect(hasSkippedOnboarding('u-2')).toBe(false)
  })
})
