import { useState } from 'react'
import { useCurrentUser } from '../hooks/useCurrentUser.ts'
import { SignInWithGoogle } from '../components/SignInWithGoogle.tsx'
import { DevModePanel, type DevRole } from '../features/auth/DevModePanel.tsx'
import { CustomerPage } from './CustomerPage.tsx'
import { TechnicianPage } from './TechnicianPage.tsx'

interface DevSession {
  role: DevRole
  uuid: string
}

export function HomePage() {
  const authState = useCurrentUser()
  const [devSession, setDevSession] = useState<DevSession | null>(null)

  if (authState.status === 'loading') {
    return <div className="loading">Checking authentication…</div>
  }

  if (authState.status === 'authenticated') {
    const { user } = authState
    if (user.role === 'technician') {
      return <TechnicianPage technicianId={user.user_id} email={user.email} />
    }
    return <CustomerPage customerId={user.user_id} email={user.email} />
  }

  if (devSession) {
    if (devSession.role === 'technician') {
      return <TechnicianPage technicianId={devSession.uuid} devMode />
    }
    return <CustomerPage customerId={devSession.uuid} devMode />
  }

  const googleUnavailable = authState.status === 'unavailable'

  return (
    <div className="home-page">
      <div className="home-page__hero">
        <h1>Field Service Management</h1>
        <p>Schedule and manage field service appointments.</p>
      </div>

      {googleUnavailable ? (
        <div className="home-page__auth-unavailable">
          <p className="notice notice--warn">
            Google sign-in is not configured on this server. Use dev mode below to proceed.
          </p>
          <DevModePanel onEnter={(role, uuid) => setDevSession({ role, uuid })} />
        </div>
      ) : (
        <div className="home-page__auth">
          <SignInWithGoogle />
          <button
            className="btn btn-link"
            onClick={() => setDevSession({ role: 'customer', uuid: '' })}
          >
            Use dev mode instead
          </button>
        </div>
      )}

      {!googleUnavailable && (
        <div className="home-page__dev-toggle">
          <details>
            <summary>Developer mode</summary>
            <DevModePanel onEnter={(role, uuid) => setDevSession({ role, uuid })} />
          </details>
        </div>
      )}
    </div>
  )
}
