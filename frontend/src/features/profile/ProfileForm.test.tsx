import { beforeEach, describe, expect, it, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { AuthContext } from '../auth/authContext.ts'
import type { CurrentUser } from '../../api/types.ts'

vi.mock('../../api/auth.ts', () => ({
  updateProfile: vi.fn().mockResolvedValue({}),
}))
import { updateProfile } from '../../api/auth.ts'
import { ProfileForm } from './ProfileForm.tsx'

const baseUser: CurrentUser = {
  user_id: 'u-1',
  email: 'c@example.com',
  role: 'CUSTOMER',
  role_status: 'APPROVED',
  name: 'Google Name',
  display_name: null,
  address: '12 Main St',
  phone: null,
}

function renderForm(
  opts: { onSkip?: () => void; requiredFields?: Array<'address' | 'phone'>; user?: CurrentUser } = {},
) {
  const refresh = vi.fn()
  const onSaved = vi.fn()
  const user = opts.user ?? baseUser
  render(
    <AuthContext.Provider
      value={{ auth: { status: 'authenticated', user }, refresh }}
    >
      <ProfileForm
        user={user}
        onSaved={onSaved}
        onSkip={opts.onSkip}
        requiredFields={opts.requiredFields}
      />
    </AuthContext.Provider>,
  )
  return { refresh, onSaved }
}

beforeEach(() => vi.mocked(updateProfile).mockClear())

describe('ProfileForm', () => {
  it('seeds inputs from the current user', () => {
    renderForm()
    expect(screen.getByLabelText(/service address/i)).toHaveValue('12 Main St')
    expect(screen.getByLabelText(/phone/i)).toHaveValue('')
  })

  it('submits only the fields the user changed', async () => {
    const { refresh, onSaved } = renderForm()
    await userEvent.type(screen.getByLabelText(/phone/i), '054-7586288')
    await userEvent.click(screen.getByRole('button', { name: /save/i }))

    expect(updateProfile).toHaveBeenCalledWith({ phone: '054-7586288' })
    expect(refresh).toHaveBeenCalled()
    expect(onSaved).toHaveBeenCalled()
  })

  it('sends an empty string when a field is cleared', async () => {
    renderForm()
    await userEvent.clear(screen.getByLabelText(/service address/i))
    await userEvent.click(screen.getByRole('button', { name: /save/i }))

    expect(updateProfile).toHaveBeenCalledWith({ address: '' })
  })

  it('skips the API call when nothing changed', async () => {
    const { onSaved } = renderForm()
    await userEvent.click(screen.getByRole('button', { name: /save/i }))

    expect(updateProfile).not.toHaveBeenCalled()
    expect(onSaved).toHaveBeenCalled()
  })

  it('blocks the save and warns when a required field is blank', async () => {
    const { onSaved } = renderForm({ requiredFields: ['address', 'phone'] })
    // baseUser has an address but no phone, so the required phone is missing.
    await userEvent.click(screen.getByRole('button', { name: /save/i }))

    expect(updateProfile).not.toHaveBeenCalled()
    expect(onSaved).not.toHaveBeenCalled()
    expect(screen.getByText(/before booking/i)).toBeInTheDocument()
  })

  it('omits the customer-only "before booking" wording for a technician', async () => {
    const technician: CurrentUser = { ...baseUser, role: 'TECHNICIAN', phone: null }
    const { onSaved } = renderForm({ requiredFields: ['phone'], user: technician })
    await userEvent.click(screen.getByRole('button', { name: /save/i }))

    expect(updateProfile).not.toHaveBeenCalled()
    expect(onSaved).not.toHaveBeenCalled()
    expect(screen.queryByText(/before booking/i)).toBeNull()
    expect(screen.getByText(/complete your profile/i)).toBeInTheDocument()
  })

  it('rejects a clearly-malformed phone number on submit', async () => {
    const { onSaved } = renderForm()
    await userEvent.type(screen.getByLabelText(/phone/i), '123')
    await userEvent.click(screen.getByRole('button', { name: /save/i }))

    expect(updateProfile).not.toHaveBeenCalled()
    expect(onSaved).not.toHaveBeenCalled()
    expect(screen.getByText(/valid phone/i)).toBeInTheDocument()
  })

  it('warns about a non-Israeli number but still allows saving it', async () => {
    const { onSaved } = renderForm()
    await userEvent.type(screen.getByLabelText(/phone/i), '+1-202-555-0143')
    // The warning appears live, before submitting.
    expect(screen.getByText(/israeli/i)).toBeInTheDocument()

    await userEvent.click(screen.getByRole('button', { name: /save/i }))

    expect(updateProfile).toHaveBeenCalledWith({ phone: '+1-202-555-0143' })
    expect(onSaved).toHaveBeenCalled()
  })

  it('saves once every required field is filled', async () => {
    const { onSaved } = renderForm({ requiredFields: ['address', 'phone'] })
    await userEvent.type(screen.getByLabelText(/phone/i), '054-7586288')
    await userEvent.click(screen.getByRole('button', { name: /save/i }))

    expect(updateProfile).toHaveBeenCalledWith({ phone: '054-7586288' })
    expect(onSaved).toHaveBeenCalled()
  })

  it('renders Skip only when onSkip is provided, and fires it', async () => {
    renderForm()
    expect(screen.queryByRole('button', { name: /skip/i })).toBeNull()

    const onSkip = vi.fn()
    renderForm({ onSkip })
    await userEvent.click(screen.getByRole('button', { name: /skip/i }))
    expect(onSkip).toHaveBeenCalled()
  })
})
