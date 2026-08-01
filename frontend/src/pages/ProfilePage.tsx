import { Link, Navigate, useNavigate } from 'react-router-dom'
import { useAuth } from '../features/auth/authContext.ts'
import { ProfileForm } from '../features/profile/ProfileForm.tsx'
import { PageHeader } from '../features/layout/PageHeader.tsx'

export function ProfilePage() {
  const { auth } = useAuth()
  const navigate = useNavigate()

  if (auth.status === 'loading') {
    return <div className="loading">Checking authentication…</div>
  }
  if (auth.status !== 'authenticated') {
    return <Navigate to="/" replace />
  }

  const { user } = auth
  return (
    <div className="page">
      <PageHeader title="Your profile" />
      <ProfileForm user={user} onSaved={() => navigate('/')} />
      <div className="page__nav">
        <Link to="/" className="btn btn-secondary">
          Back
        </Link>
      </div>
    </div>
  )
}
