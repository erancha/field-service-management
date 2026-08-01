import { describe, expect, it } from 'vitest'
import { render, screen } from '@testing-library/react'
import { PageHeader } from './PageHeader.tsx'

describe('PageHeader', () => {
  it('renders the title with the account id as its tooltip', () => {
    render(<PageHeader title="Customer Dashboard" accountId="c-42" />)

    const heading = screen.getByRole('heading', { name: 'Customer Dashboard' })
    expect(heading).toHaveAttribute('title', 'c-42')
  })

  it('renders only the title — user controls live in the app shell', () => {
    render(<PageHeader title="Back office" />)

    expect(screen.getByRole('heading', { name: 'Back office' })).toBeInTheDocument()
    expect(screen.queryByRole('button')).toBeNull()
    expect(screen.queryByRole('link')).toBeNull()
  })
})
