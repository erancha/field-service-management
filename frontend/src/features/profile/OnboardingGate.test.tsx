import { beforeEach, describe, expect, it, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { AuthContext } from '../auth/authContext.ts'
import type { CurrentUser } from '../../api/types.ts'

vi.mock('../../api/auth.ts', () => ({
  updateProfile: vi.fn().mockResolvedValue({}),
}))
import { OnboardingGate } from './OnboardingGate.tsx'

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

function renderGate(u: CurrentUser) {
  render(
    <AuthContext.Provider value={{ auth: { status: 'authenticated', user: u }, refresh: vi.fn() }}>
      <OnboardingGate user={u}>
        <div>customer dashboard</div>
      </OnboardingGate>
    </AuthContext.Provider>,
  )
}

beforeEach(() => sessionStorage.clear())

describe('OnboardingGate', () => {
  it('shows the onboarding form for an incomplete customer profile', () => {
    renderGate(user())
    expect(screen.getByText(/almost there/i)).toBeInTheDocument()
    expect(screen.queryByText('customer dashboard')).toBeNull()
  })

  it('renders children when the profile is complete', () => {
    renderGate(user({ address: '12 Main St', phone: '+972-50' }))
    expect(screen.getByText('customer dashboard')).toBeInTheDocument()
  })

  it('renders children after skip and persists the skip for the session', async () => {
    renderGate(user())
    await userEvent.click(screen.getByRole('button', { name: /skip/i }))
    expect(screen.getByText('customer dashboard')).toBeInTheDocument()
    expect(sessionStorage.getItem('fsm-onboarding-skipped:u-1')).toBe('1')
  })

  it('renders children immediately when previously skipped this session', () => {
    sessionStorage.setItem('fsm-onboarding-skipped:u-1', '1')
    renderGate(user())
    expect(screen.getByText('customer dashboard')).toBeInTheDocument()
  })

  it('dismisses on the save event itself even though the user prop is still stale', async () => {
    // refresh() is synchronous-fire/async-resolve: the `user` prop passed back in still
    // reads as needing onboarding immediately after a successful save. The gate must
    // dismiss from the form's onSaved event, not by re-deriving needsOnboarding(user).
    renderGate(user())
    await userEvent.type(screen.getByLabelText(/service address/i), '12 Main St')
    await userEvent.type(screen.getByLabelText(/phone/i), '+972-50')
    await userEvent.click(screen.getByRole('button', { name: 'Save' }))
    expect(await screen.findByText('customer dashboard')).toBeInTheDocument()
    expect(screen.queryByText(/almost there/i)).toBeNull()
  })
})
