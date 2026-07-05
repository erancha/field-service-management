import { Link } from 'react-router-dom'
import { LogoutButton } from '../auth/LogoutButton.tsx'

interface PageHeaderProps {
  title: string
  email?: string
  // The profile page itself opts out; every other page links to it.
  profileLink?: boolean
}

/**
 * Shared page chrome: the title row with the signed-in email, a link to the profile
 * page, and the sign-out button.
 */
export function PageHeader({ title, email, profileLink = true }: PageHeaderProps) {
  return (
    <header className="page__header">
      <h2>{title}</h2>
      <div className="page__header-right">
        {email && <span className="page__email">{email}</span>}
        {profileLink && (
          <Link to="/profile" className="btn btn-secondary">
            Profile
          </Link>
        )}
        <LogoutButton />
      </div>
    </header>
  )
}
