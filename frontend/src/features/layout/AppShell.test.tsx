import { describe, expect, it, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import type { CurrentUserResult } from '../../hooks/useCurrentUser.ts'
import type { CurrentUser } from '../../api/types.ts'
import { AppShell } from './AppShell.tsx'
import { AuthContext } from '../auth/authContext.ts'
import { BRAND } from '../../constants.ts'

const USER: CurrentUser = {
  user_id: 'u-1',
  email: 'jane@example.com',
  role: 'CUSTOMER',
  role_status: 'APPROVED',
  name: 'Jane',
  display_name: null,
  address: null,
  phone: null,
  assist_disclaimer_accepted_at: null,
}

function renderShell(auth: CurrentUserResult['auth'], route = '/') {
  render(
    <MemoryRouter initialEntries={[route]}>
      <AuthContext.Provider value={{ auth, refresh: vi.fn() }}>
        <AppShell>
          <div>page content</div>
        </AppShell>
      </AuthContext.Provider>
    </MemoryRouter>,
  )
}

describe('AppShell', () => {
  it('shows the brand and the page content without user controls when signed out', () => {
    renderShell({ status: 'unauthenticated' })

    expect(screen.getByText(BRAND)).toBeInTheDocument()
    expect(screen.getByText('page content')).toBeInTheDocument()
    expect(screen.queryByRole('link', { name: 'Profile' })).toBeNull()
    expect(screen.queryByRole('button', { name: /sign out/i })).toBeNull()
  })

  it('shows the email, profile link, and sign-out button for a signed-in user', () => {
    renderShell({ status: 'authenticated', user: USER })

    expect(screen.getByText(BRAND)).toBeInTheDocument()
    expect(screen.getByText('jane@example.com')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Profile' })).toHaveAttribute('href', '/profile')
    expect(screen.getByRole('button', { name: /sign out/i })).toBeInTheDocument()
  })

  it('hides the profile link while already on the profile page', () => {
    renderShell({ status: 'authenticated', user: USER }, '/profile')

    expect(screen.queryByRole('link', { name: 'Profile' })).toBeNull()
    expect(screen.getByRole('button', { name: /sign out/i })).toBeInTheDocument()
  })
})
