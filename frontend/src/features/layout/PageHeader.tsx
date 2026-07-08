import { Link } from 'react-router-dom'
import { LogoutButton } from '../auth/LogoutButton.tsx'

interface PageHeaderProps {
  title: string
  email?: string
  // Account identifier surfaced only as a hover tooltip on the title, keeping the rarely needed id
  // out of the visible layout.
  accountId?: string
  // The profile page itself opts out; every other page links to it.
  profileLink?: boolean
}

/**
 * Shared page chrome: the title row with the signed-in email, a link to the profile
 * page, and the sign-out button.
 */
export function PageHeader({ title, email, accountId, profileLink = true }: PageHeaderProps) {
  return (
    <header className="page__header">
      <h2 title={accountId}>{title}</h2>
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
