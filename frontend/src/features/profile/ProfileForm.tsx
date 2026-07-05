import { useState } from 'react'
import { updateProfile } from '../../api/auth.ts'
import type { CurrentUser, ProfileUpdate } from '../../api/types.ts'
import { useAuth } from '../auth/authContext.ts'
import { isValidPhone, isIsraeliPhone } from './phone.ts'
import { Button } from '../../components/Button.tsx'
import { ErrorBanner } from '../../components/ErrorBanner.tsx'
import { errorMessage } from '../../utils/errors.ts'

interface ProfileFormProps {
  user: CurrentUser
  onSaved: () => void
  onSkip?: () => void
  // Fields that must be non-blank before the profile can be saved. Empty by default so the
  // standalone profile page stays freely editable; the onboarding gate passes the fields a
  // booking depends on so an incomplete profile cannot be saved past it.
  requiredFields?: Array<'address' | 'phone'>
}

const FIELD_LABELS: Record<'address' | 'phone', string> = {
  address: 'service address',
  phone: 'phone',
}

export function ProfileForm({ user, onSaved, onSkip, requiredFields = [] }: ProfileFormProps) {
  const { refresh } = useAuth()
  const [displayName, setDisplayName] = useState(user.display_name ?? '')
  const [address, setAddress] = useState(user.address ?? '')
  const [phone, setPhone] = useState(user.phone ?? '')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  // A well-formed number that is not a valid Israeli number is allowed but flagged, since most
  // users are Israeli and a foreign-looking number is more often a typo than intentional.
  const showsNonIsraeliWarning =
    phone.trim() !== '' && isValidPhone(phone) && !isIsraeliPhone(phone)

  function changedFields(): ProfileUpdate {
    const patch: ProfileUpdate = {}
    if (displayName !== (user.display_name ?? '')) patch.display_name = displayName
    if (address !== (user.address ?? '')) patch.address = address
    if (phone !== (user.phone ?? '')) patch.phone = phone
    return patch
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    const values = { address, phone }
    const missing = requiredFields.filter((field) => !values[field].trim())
    if (missing.length > 0) {
      const fields = missing.map((f) => FIELD_LABELS[f]).join(' and ')
      // Only the customer books; the technician supplies contact so a booked customer can reach them.
      const reason = user.role === 'CUSTOMER' ? 'before booking' : 'to complete your profile'
      setError(`Please add your ${fields} ${reason}.`)
      return
    }
    if (phone.trim() && !isValidPhone(phone)) {
      setError('Please enter a valid phone number.')
      return
    }
    // A non-Israeli but well-formed number is allowed; the inline warning already flagged it.
    const patch = changedFields()
    if (Object.keys(patch).length === 0) {
      onSaved()
      return
    }
    setError(null)
    setLoading(true)
    try {
      await updateProfile(patch)
      refresh()
      onSaved()
    } catch (err) {
      setError(errorMessage(err, 'Failed to save profile'))
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="profile-form">
      <ErrorBanner message={error} onDismiss={() => setError(null)} />
      <form onSubmit={handleSubmit} className="form">
        <label>
          Preferred name:
          <input
            value={displayName}
            onChange={(e) => setDisplayName(e.target.value)}
            placeholder={user.name}
          />
        </label>
        <label>
          Service address:
          <input
            value={address}
            onChange={(e) => setAddress(e.target.value)}
            placeholder="Where should the technician go?"
          />
        </label>
        <label>
          Phone:
          <input
            value={phone}
            onChange={(e) => setPhone(e.target.value)}
            placeholder="How can we reach you?"
          />
        </label>
        {showsNonIsraeliWarning && (
          <p className="profile-form__warning" role="status">
            This doesn't look like an Israeli number — please double-check it.
          </p>
        )}
        <div className="profile-form__actions">
          <Button type="submit" loading={loading}>
            Save
          </Button>
          {onSkip && (
            <Button type="button" variant="secondary" onClick={onSkip}>
              Skip for now
            </Button>
          )}
        </div>
      </form>
    </div>
  )
}
