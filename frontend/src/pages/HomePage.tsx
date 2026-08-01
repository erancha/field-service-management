import { useAuth } from '../features/auth/authContext.ts'
import { SignInWithGoogle } from '../components/SignInWithGoogle.tsx'
import { CustomerPage } from './CustomerPage.tsx'
import { TechnicianPage } from './TechnicianPage.tsx'
import { AdminPage } from './AdminPage.tsx'
import { TechnicianWaiting } from '../features/technician/TechnicianWaiting.tsx'
import { TechnicianDeclined } from '../features/technician/TechnicianDeclined.tsx'
import { OnboardingGate } from '../features/profile/OnboardingGate.tsx'
import { AssistDisclaimerGate } from '../features/customer/AssistDisclaimerGate.tsx'

export function HomePage() {
  const { auth, refresh } = useAuth()

  if (auth.status === 'loading') {
    return <div className="loading">Checking authentication…</div>
  }

  if (auth.status === 'error') {
    return (
      <div className="home-page__error" role="alert">
        Couldn't check your sign-in status. Please refresh the page to try again.
      </div>
    )
  }

  if (auth.status === 'authenticated') {
    const { user } = auth

    if (user.role === 'ADMIN') {
      return <AdminPage />
    }

    if (user.role === 'TECHNICIAN') {
      if (user.role_status === 'APPROVED') {
        return (
          <OnboardingGate user={user}>
            <TechnicianPage technicianId={user.user_id} />
          </OnboardingGate>
        )
      }
      if (user.role_status === 'REJECTED') {
        return <TechnicianDeclined />
      }
      return <TechnicianWaiting userId={user.user_id} onDecided={refresh} />
    }

    return (
      <AssistDisclaimerGate user={user}>
        <OnboardingGate user={user}>
          <CustomerPage customerId={user.user_id} />
        </OnboardingGate>
      </AssistDisclaimerGate>
    )
  }

  return (
    <div className="home-page">
      <p className="home-page__tagline">Schedule and manage field service appointments.</p>
      <div className="home-page__auth">
        <SignInWithGoogle />
      </div>
    </div>
  )
}
