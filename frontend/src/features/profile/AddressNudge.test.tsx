import { describe, expect, it, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { AuthContext } from '../auth/authContext.ts'
import type { CurrentUser } from '../../api/types.ts'
import { AddressNudge } from './AddressNudge.tsx'

function renderNudge(address: string | null, phone: string | null = '054-1234567') {
  const user: CurrentUser = {
    user_id: 'u-1',
    email: 'c@example.com',
    role: 'CUSTOMER',
    role_status: 'APPROVED',
    name: 'Google Name',
    display_name: null,
    address,
    phone,
    assist_disclaimer_accepted_at: null,
  }
  render(
    <AuthContext.Provider value={{ auth: { status: 'authenticated', user }, refresh: vi.fn() }}>
      <MemoryRouter>
        <AddressNudge />
      </MemoryRouter>
    </AuthContext.Provider>,
  )
}

describe('AddressNudge', () => {
  it('shows the banner with a profile link when the address is missing', () => {
    renderNudge(null)
    expect(screen.getByText(/before booking/i)).toBeInTheDocument()
    expect(screen.getByRole('link', { name: /profile/i })).toHaveAttribute('href', '/profile')
  })

  it('shows the banner when the address is whitespace-only', () => {
    renderNudge('   ')
    expect(screen.getByText(/before booking/i)).toBeInTheDocument()
  })

  it('shows the banner when the phone is missing even if the address is set', () => {
    renderNudge('12 Main St', null)
    expect(screen.getByText(/before booking/i)).toBeInTheDocument()
  })

  it('renders nothing when both address and phone are set', () => {
    renderNudge('12 Main St', '054-1234567')
    expect(screen.queryByText(/before booking/i)).toBeNull()
  })

  it('hides after dismissal', async () => {
    renderNudge(null)
    await userEvent.click(screen.getByRole('button', { name: /dismiss/i }))
    expect(screen.queryByText(/before booking/i)).toBeNull()
  })
})
