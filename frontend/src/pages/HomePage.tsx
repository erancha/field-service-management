import { useCurrentUser } from '../hooks/useCurrentUser.ts'
import { SignInWithGoogle } from '../components/SignInWithGoogle.tsx'
import { CustomerPage } from './CustomerPage.tsx'
import { TechnicianPage } from './TechnicianPage.tsx'

export function HomePage() {
  const authState = useCurrentUser()

  if (authState.status === 'loading') {
    return <div className="loading">Checking authentication…</div>
  }

  if (authState.status === 'authenticated') {
    const { user } = authState
    if (user.role === 'TECHNICIAN') {
      return <TechnicianPage technicianId={user.user_id} email={user.email} />
    }
    return <CustomerPage customerId={user.user_id} email={user.email} />
  }

  return (
    <div className="home-page">
      <div className="home-page__hero">
        <h1>Field Service Management</h1>
        <p>Schedule and manage field service appointments.</p>
      </div>
      <div className="home-page__auth">
        <SignInWithGoogle />
      </div>
    </div>
  )
}
