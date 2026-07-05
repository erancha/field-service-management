import { describe, expect, it, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import type { ReactElement } from 'react'
import { PageHeader } from './PageHeader.tsx'
import { AuthContext } from '../auth/authContext.ts'

function renderHeader(ui: ReactElement) {
  render(
    <MemoryRouter>
      <AuthContext.Provider value={{ auth: { status: 'loading' }, refresh: vi.fn() }}>
        {ui}
      </AuthContext.Provider>
    </MemoryRouter>,
  )
}

describe('PageHeader', () => {
  it('renders the title, email, profile link, and sign-out button', () => {
    renderHeader(<PageHeader title="Customer Dashboard" email="jane@example.com" />)

    expect(screen.getByRole('heading', { name: 'Customer Dashboard' })).toBeInTheDocument()
    expect(screen.getByText('jane@example.com')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Profile' })).toHaveAttribute('href', '/profile')
    expect(screen.getByRole('button', { name: /sign out/i })).toBeInTheDocument()
  })

  it('omits the email when none is provided', () => {
    renderHeader(<PageHeader title="Back office" />)

    expect(document.querySelector('.page__email')).toBeNull()
  })

  it('omits the profile link when profileLink is false', () => {
    renderHeader(<PageHeader title="Your profile" email="jane@example.com" profileLink={false} />)

    expect(screen.queryByRole('link', { name: 'Profile' })).toBeNull()
    expect(screen.getByRole('button', { name: /sign out/i })).toBeInTheDocument()
  })
})
