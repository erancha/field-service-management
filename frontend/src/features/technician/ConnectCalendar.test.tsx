import { describe, expect, it } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { ConnectCalendar } from './ConnectCalendar.tsx'

function renderConnect(
  status: 'loading' | 'disconnected',
  initialUrl = '/',
) {
  render(
    <MemoryRouter initialEntries={[initialUrl]}>
      <ConnectCalendar status={status} />
    </MemoryRouter>,
  )
}

describe('ConnectCalendar', () => {
  it('shows a rejection banner plus the retry link when redirected back with calendar_connect=denied', () => {
    renderConnect('disconnected', '/?calendar_connect=denied')
    expect(screen.getByRole('alert')).toHaveTextContent(/calendar permissions weren.t granted/i)
    // The existing Connect link is the retry affordance.
    expect(screen.getByRole('link', { name: /connect google calendar/i })).toHaveAttribute(
      'href',
      '/calendar/connect/login',
    )
  })

  it('shows no banner on a normal disconnected view', () => {
    renderConnect('disconnected', '/')
    expect(screen.queryByRole('alert')).toBeNull()
  })

  it('hides the banner after dismissal', async () => {
    renderConnect('disconnected', '/?calendar_connect=denied')
    await userEvent.click(screen.getByRole('button', { name: /dismiss/i }))
    expect(screen.queryByRole('alert')).toBeNull()
  })
})
