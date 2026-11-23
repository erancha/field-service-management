import { fireEvent, render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it, vi } from 'vitest'
import { AuthContext } from '../features/auth/authContext.ts'
import { HomePage } from './HomePage.tsx'

vi.mock('../api/auth.ts', () => ({ startGoogleSignIn: vi.fn() }))

function renderSignedOut() {
  return render(
    <MemoryRouter>
      <AuthContext.Provider value={{ auth: { status: 'unauthenticated' }, refresh: vi.fn() }}>
        <HomePage />
      </AuthContext.Provider>
    </MemoryRouter>,
  )
}

describe('HomePage signed out', () => {
  it('heads the card with the icon, the product name and the tagline', () => {
    const { container } = renderSignedOut()

    const heading = screen.getByRole('heading', {
      level: 1,
      name: 'Field Service Management',
    })
    expect(heading.closest('main.landing > .landing-card')).not.toBeNull()
    expect(heading.querySelector('img.app-icon')).toHaveAttribute('src', '/favicon.svg')
    // The name is long, so the heading takes the size that keeps it on one line on a phone.
    expect(heading).toHaveClass('app-heading-long')
    expect(screen.getByText('AI-assisted service calls')).toHaveClass('app-tagline')
    // The build makes no stamp, so no line names the build.
    expect(container.querySelector('.app-version')).toBeNull()
  })

  it('pitches the product in plain lines and three numbered steps', () => {
    const { container } = renderSignedOut()

    expect(container.querySelectorAll('.landing-pitch')).toHaveLength(2)
    expect(screen.getByText('Report a fault in a chat.').tagName).toBe('STRONG')
    const steps = container.querySelectorAll('.landing-steps > li')
    expect(steps).toHaveLength(3)
    expect(steps[0]).toHaveTextContent(/^Describe the fault: /)
    expect(steps[1]).toHaveTextContent(/^Try a safe fix first: /)
    expect(steps[2]).toHaveTextContent(/^Book a visit if needed: /)
  })

  it('adds the details under the pitch from the More toggle', async () => {
    const user = userEvent.setup()
    const { container } = renderSignedOut()
    const more = screen.getByRole('button', { name: 'More' })
    expect(more).toHaveAttribute('aria-expanded', 'false')
    expect(container.querySelector('.landing-card > .landing-details')).toBeNull()

    await user.click(more)

    const less = screen.getByRole('button', { name: 'Less' })
    expect(less).toHaveAttribute('aria-expanded', 'true')
    const details = container.querySelector('.landing-card > .landing-details')
    expect(details?.nextElementSibling).toBe(less)
    expect(within(details as HTMLElement).getByText(/the manual page/)).toBeInTheDocument()
  })

  it('opening the sign-in explanation folds the details back', async () => {
    renderSignedOut()
    const more = screen.getByRole('button', { name: 'More' })
    fireEvent.click(more)
    fireEvent.click(document.querySelector('.sign-in-why') as HTMLElement)
    expect(document.querySelector('.landing-card > .landing-details')).toBeNull()
    expect(more).toHaveAttribute('aria-expanded', 'false')
  })

  it('links under the card to the walkthrough, the WhatsApp invite and the source', () => {
    const { container } = renderSignedOut()

    const footer = container.querySelector('main.landing > footer.landing-links') as HTMLElement
    const links = within(footer).getAllByRole('link')
    expect(links).toHaveLength(3)
    const [walkthrough, invite, source] = links
    expect(walkthrough).toHaveAccessibleName('Visual walkthrough')
    expect(walkthrough.querySelector('.link-mark')).toHaveTextContent('▶️')
    expect(walkthrough).toHaveAttribute(
      'href',
      'https://erancha.github.io/field-service-management/samples/walkthrough/',
    )
    expect(walkthrough).toHaveAttribute('target', '_blank')
    expect(walkthrough).toHaveAttribute('rel', 'noreferrer')
    expect(invite).toHaveAccessibleName('Invite friends on WhatsApp')
    expect(invite.querySelector('.link-mark')).toHaveTextContent('💬')
    expect(invite).toHaveAttribute('target', '_blank')
    expect(invite).toHaveAttribute('rel', 'noreferrer')
    const url = new URL(invite.getAttribute('href') as string)
    expect(`${url.origin}${url.pathname}`).toBe('https://wa.me/')
    const paragraphs = (url.searchParams.get('text') as string).split('\n\n')
    expect(paragraphs[0]).toMatch(/^Hi! 👋 I got a recommendation for Field Service Management/)
    expect(paragraphs[paragraphs.length - 1]).toMatch(new RegExp(`\n${window.location.origin}$`))
    expect(source).toHaveAccessibleName('Source code on GitHub')
    expect(source).toHaveAttribute('href', 'https://github.com/erancha/field-service-management')
    expect(source).toHaveAttribute('target', '_blank')
    expect(source).toHaveAttribute('rel', 'noreferrer')
  })

  it('places the shared sign-in button inside the card', () => {
    renderSignedOut()

    const button = screen.getByRole('button', { name: 'Sign in with Google' })
    expect(button).toHaveClass('sign-in-button')
    expect(button.closest('.landing-card > .sign-in')).not.toBeNull()
  })
})
