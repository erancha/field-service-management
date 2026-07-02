import { useState } from 'react'
import { Link } from 'react-router-dom'
import { useAuth } from '../auth/authContext.ts'

export function AddressNudge() {
  const { auth } = useAuth()
  const [dismissed, setDismissed] = useState(false)

  // Backend strips the address before using it as the event location, so a whitespace-only
  // value yields no usable location — treat it the same as blank and keep nudging.
  if (dismissed || auth.status !== 'authenticated' || auth.user.address?.trim()) return null

  return (
    <div className="nudge">
      <span>Add your address so the technician can find you.</span>
      <Link to="/profile" className="btn btn-secondary">
        Add address
      </Link>
      <button className="nudge__dismiss" onClick={() => setDismissed(true)} aria-label="Dismiss">
        ×
      </button>
    </div>
  )
}
