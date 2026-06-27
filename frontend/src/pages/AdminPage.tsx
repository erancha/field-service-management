import { LogoutButton } from '../features/auth/LogoutButton.tsx'
import { TechnicianRequestQueue } from '../features/backoffice/TechnicianRequestQueue.tsx'

interface AdminPageProps {
  email?: string
}

export function AdminPage({ email }: AdminPageProps) {
  return (
    <div className="page">
      <header className="page__header">
        <h2>Back office</h2>
        <div className="page__header-right">
          {email && <span className="page__email">{email}</span>}
          <LogoutButton />
        </div>
      </header>

      <TechnicianRequestQueue />
    </div>
  )
}
