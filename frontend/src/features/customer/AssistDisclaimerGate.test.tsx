import { beforeEach, describe, expect, it, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import type { CurrentUser } from '../../api/types.ts'
import { BRAND } from '../../constants.ts'

const acceptAssistDisclaimer = vi.fn()
vi.mock('../../api/auth.ts', () => ({
  acceptAssistDisclaimer: (...args: unknown[]) => acceptAssistDisclaimer(...args),
}))
import { AssistDisclaimerGate } from './AssistDisclaimerGate.tsx'

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
    assist_disclaimer_accepted_at: null,
    ...overrides,
  }
}

function renderGate(u: CurrentUser) {
  render(
    <AssistDisclaimerGate user={u}>
      <div>customer dashboard</div>
    </AssistDisclaimerGate>,
  )
}

beforeEach(() => {
  acceptAssistDisclaimer.mockReset()
  acceptAssistDisclaimer.mockResolvedValue(user({ assist_disclaimer_accepted_at: 'now' }))
})

describe('AssistDisclaimerGate', () => {
  it('holds a customer who has never accepted, showing the limits and the safety boundary', () => {
    renderGate(user())
    expect(screen.getByRole('heading', { level: 1 })).toHaveTextContent(/before you start/i)
    expect(screen.getByText(BRAND)).toBeInTheDocument()
    expect(screen.getByText(/knowledge base first/i)).toBeInTheDocument()
    expect(screen.getByText(/cut-off date/i)).toBeInTheDocument()
    expect(screen.getByText(/anything risky/i)).toBeInTheDocument()
    expect(screen.queryByText('customer dashboard')).toBeNull()
  })

  it('keeps Continue disabled until the confirmation is ticked', async () => {
    renderGate(user())
    const button = screen.getByRole('button', { name: /continue/i })
    expect(button).toBeDisabled()

    await userEvent.click(screen.getByRole('checkbox'))
    expect(button).toBeEnabled()
  })

  it('records the acceptance and reveals the dashboard', async () => {
    renderGate(user())
    await userEvent.click(screen.getByRole('checkbox'))
    await userEvent.click(screen.getByRole('button', { name: /continue/i }))

    expect(acceptAssistDisclaimer).toHaveBeenCalledOnce()
    expect(await screen.findByText('customer dashboard')).toBeInTheDocument()
  })

  it('renders children without a call when the account already accepted', () => {
    renderGate(user({ assist_disclaimer_accepted_at: '2026-08-01T09:00:00+00:00' }))
    expect(screen.getByText('customer dashboard')).toBeInTheDocument()
    expect(acceptAssistDisclaimer).not.toHaveBeenCalled()
  })

  it('holds the gate up when the acceptance could not be recorded', async () => {
    acceptAssistDisclaimer.mockRejectedValue(new Error('network down'))
    renderGate(user())
    await userEvent.click(screen.getByRole('checkbox'))
    await userEvent.click(screen.getByRole('button', { name: /continue/i }))

    expect(await screen.findByRole('alert')).toHaveTextContent(/could not record/i)
    expect(screen.queryByText('customer dashboard')).toBeNull()
  })
})
