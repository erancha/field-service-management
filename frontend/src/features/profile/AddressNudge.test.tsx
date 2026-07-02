import { describe, expect, it, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { AuthContext } from '../auth/authContext.ts'
import type { CurrentUser } from '../../api/types.ts'
import { AddressNudge } from './AddressNudge.tsx'

function renderNudge(address: string | null) {
  const user: CurrentUser = {
    user_id: 'u-1',
    email: 'c@example.com',
    role: 'CUSTOMER',
    role_status: 'APPROVED',
    name: 'Google Name',
    display_name: null,
    address,
    phone: null,
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
    expect(screen.getByText(/add your address/i)).toBeInTheDocument()
    expect(screen.getByRole('link', { name: /add address/i })).toHaveAttribute('href', '/profile')
  })

  it('shows the banner when the address is whitespace-only', () => {
    renderNudge('   ')
    expect(screen.getByText(/add your address/i)).toBeInTheDocument()
  })

  it('renders nothing when the address is set', () => {
    renderNudge('12 Main St')
    expect(screen.queryByText(/add your address/i)).toBeNull()
  })

  it('hides after dismissal', async () => {
    renderNudge(null)
    await userEvent.click(screen.getByRole('button', { name: /dismiss/i }))
    expect(screen.queryByText(/add your address/i)).toBeNull()
  })
})
