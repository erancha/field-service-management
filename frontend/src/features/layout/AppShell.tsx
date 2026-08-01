import { Link, useLocation } from 'react-router-dom'
import { useAuth } from '../auth/authContext.ts'
import { LogoutButton } from '../auth/LogoutButton.tsx'
import { BRAND } from '../../constants.ts'

interface AppShellProps {
  children: React.ReactNode
}

/**
 * Global chrome rendered once around every route: the brand bar with the product name and, for a
 * signed-in user, their email, a link to the profile page, and the sign-out button. Pages render
 * only their own title and content below it.
 */
export function AppShell({ children }: AppShellProps) {
  const { auth } = useAuth()
  const location = useLocation()

  return (
    <>
      <div className="app-shell__bar">
        <div className="app-shell__brand">
          <img className="app-shell__logo" src="/favicon.svg" alt="" />
          <span>{BRAND}</span>
        </div>
        {auth.status === 'authenticated' && (
          <div className="app-shell__user">
            <span className="app-shell__email">{auth.user.email}</span>
            {location.pathname !== '/profile' && (
              <Link to="/profile" className="btn btn-secondary">
                Profile
              </Link>
            )}
            <LogoutButton />
          </div>
        )}
      </div>
      {children}
    </>
  )
}
