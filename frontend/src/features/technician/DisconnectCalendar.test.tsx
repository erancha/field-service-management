import { beforeEach, describe, expect, it, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

vi.mock('../../api/calendar.ts', () => ({
  disconnectCalendar: vi.fn(),
}))
import { disconnectCalendar } from '../../api/calendar.ts'
import { DisconnectCalendar } from './DisconnectCalendar.tsx'

describe('DisconnectCalendar', () => {
  beforeEach(() => {
    vi.mocked(disconnectCalendar).mockReset()
  })

  it('confirms before disconnecting, then notifies the parent', async () => {
    vi.mocked(disconnectCalendar).mockResolvedValue(undefined)
    const onDisconnected = vi.fn()
    render(<DisconnectCalendar onDisconnected={onDisconnected} />)

    await userEvent.click(screen.getByRole('button', { name: /disconnect/i }))
    // The trigger only asks for confirmation; nothing is disconnected yet.
    expect(disconnectCalendar).not.toHaveBeenCalled()

    await userEvent.click(screen.getByRole('button', { name: /confirm/i }))

    expect(disconnectCalendar).toHaveBeenCalledOnce()
    expect(onDisconnected).toHaveBeenCalledOnce()
  })

  it('leaves the connection intact when the confirmation is cancelled', async () => {
    const onDisconnected = vi.fn()
    render(<DisconnectCalendar onDisconnected={onDisconnected} />)

    await userEvent.click(screen.getByRole('button', { name: /disconnect/i }))
    await userEvent.click(screen.getByRole('button', { name: /cancel/i }))

    expect(disconnectCalendar).not.toHaveBeenCalled()
    expect(onDisconnected).not.toHaveBeenCalled()
    expect(screen.getByRole('button', { name: /disconnect/i })).toBeInTheDocument()
  })

  it('surfaces an error and leaves the parent untouched when the call fails', async () => {
    vi.mocked(disconnectCalendar).mockRejectedValue(new Error('boom'))
    const onDisconnected = vi.fn()
    render(<DisconnectCalendar onDisconnected={onDisconnected} />)

    await userEvent.click(screen.getByRole('button', { name: /disconnect/i }))
    await userEvent.click(screen.getByRole('button', { name: /confirm/i }))

    expect(await screen.findByRole('alert')).toBeInTheDocument()
    expect(onDisconnected).not.toHaveBeenCalled()
  })
})
