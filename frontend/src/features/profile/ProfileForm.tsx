import { useState } from 'react'
import { updateProfile } from '../../api/auth.ts'
import type { CurrentUser, ProfileUpdate } from '../../api/types.ts'
import { useAuth } from '../auth/authContext.ts'
import { Button } from '../../components/Button.tsx'
import { ErrorBanner } from '../../components/ErrorBanner.tsx'

interface ProfileFormProps {
  user: CurrentUser
  onSaved: () => void
  onSkip?: () => void
}

export function ProfileForm({ user, onSaved, onSkip }: ProfileFormProps) {
  const { refresh } = useAuth()
  const [displayName, setDisplayName] = useState(user.display_name ?? '')
  const [address, setAddress] = useState(user.address ?? '')
  const [phone, setPhone] = useState(user.phone ?? '')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  function changedFields(): ProfileUpdate {
    const patch: ProfileUpdate = {}
    if (displayName !== (user.display_name ?? '')) patch.display_name = displayName
    if (address !== (user.address ?? '')) patch.address = address
    if (phone !== (user.phone ?? '')) patch.phone = phone
    return patch
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
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
      setError(err instanceof Error ? err.message : 'Failed to save profile')
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
