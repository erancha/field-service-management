import { useState } from 'react'
import { Link } from 'react-router-dom'
import { useAuth } from '../auth/authContext.ts'

export function AddressNudge() {
  const { auth } = useAuth()
  const [dismissed, setDismissed] = useState(false)

  if (dismissed || auth.status !== 'authenticated') return null
  // Booking requires an address (the technician's event location) and a phone (so they can reach
  // the customer). The backend strips both before use, so a whitespace-only value is treated as
  // blank and keeps nudging.
  const complete = Boolean(auth.user.address?.trim() && auth.user.phone?.trim())
  if (complete) return null

  return (
    <div className="nudge">
      <span>Add your address and phone so the technician can reach you before booking.</span>
      <Link to="/profile" className="btn btn-secondary">
        Complete profile
      </Link>
      <button className="nudge__dismiss" onClick={() => setDismissed(true)} aria-label="Dismiss">
        ×
      </button>
    </div>
  )
}
