import { describe, expect, it, vi } from 'vitest'
import { fireEvent, render, screen } from '@testing-library/react'
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
  it('shows only the page content when signed out, since the landing card carries the brand', () => {
    renderShell({ status: 'unauthenticated' })

    expect(screen.queryByText(BRAND)).toBeNull()
    expect(screen.getByText('page content')).toBeInTheDocument()
  })

  it('keeps the account behind a closed menu for a signed-in user', () => {
    renderShell({ status: 'authenticated', user: USER })

    expect(screen.getByText(BRAND)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Account menu' })).toHaveAttribute(
      'aria-expanded',
      'false',
    )
    expect(screen.queryByText('jane@example.com')).toBeNull()
  })

  it('opens the menu on the name, email, profile link and sign-out item', () => {
    renderShell({ status: 'authenticated', user: USER })

    fireEvent.click(screen.getByRole('button', { name: 'Account menu' }))

    expect(screen.getByText('Jane')).toBeInTheDocument()
    expect(screen.getByText('jane@example.com')).toBeInTheDocument()
    expect(screen.getByRole('menuitem', { name: 'Profile' })).toHaveAttribute('href', '/profile')
    expect(screen.getByRole('menuitem', { name: 'Sign out' })).toBeInTheDocument()
  })

  it('closes the menu on Escape', () => {
    renderShell({ status: 'authenticated', user: USER })

    fireEvent.click(screen.getByRole('button', { name: 'Account menu' }))
    fireEvent.keyDown(document, { key: 'Escape' })

    expect(screen.queryByRole('menu')).toBeNull()
  })

  it('leaves the profile item out while already on the profile page', () => {
    renderShell({ status: 'authenticated', user: USER }, '/profile')

    fireEvent.click(screen.getByRole('button', { name: 'Account menu' }))

    expect(screen.queryByRole('menuitem', { name: 'Profile' })).toBeNull()
    expect(screen.getByRole('menuitem', { name: 'Sign out' })).toBeInTheDocument()
  })
})
