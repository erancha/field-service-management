import { useAuth } from '../features/auth/authContext.ts'
import { SignInWithGoogle } from '../components/SignInWithGoogle.tsx'
import { CustomerPage } from './CustomerPage.tsx'
import { TechnicianPage } from './TechnicianPage.tsx'
import { AdminPage } from './AdminPage.tsx'
import { TechnicianWaiting } from '../features/technician/TechnicianWaiting.tsx'
import { TechnicianDeclined } from '../features/technician/TechnicianDeclined.tsx'
import { OnboardingGate } from '../features/profile/OnboardingGate.tsx'

export function HomePage() {
  const { auth, refresh } = useAuth()

  if (auth.status === 'loading') {
    return <div className="loading">Checking authentication…</div>
  }

  if (auth.status === 'authenticated') {
    const { user } = auth

    if (user.role === 'ADMIN') {
      return <AdminPage email={user.email} />
    }

    if (user.role === 'TECHNICIAN') {
      if (user.role_status === 'APPROVED') {
        return <TechnicianPage technicianId={user.user_id} email={user.email} />
      }
      if (user.role_status === 'REJECTED') {
        return <TechnicianDeclined email={user.email} />
      }
      return <TechnicianWaiting userId={user.user_id} email={user.email} onDecided={refresh} />
    }

    return (
      <OnboardingGate user={user}>
        <CustomerPage customerId={user.user_id} email={user.email} />
      </OnboardingGate>
    )
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
