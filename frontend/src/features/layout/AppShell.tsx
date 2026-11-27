import { useAuth } from '../auth/authContext.ts'
import { BRAND } from '../../constants.ts'
import { AccountMenu } from './AccountMenu.tsx'

interface AppShellProps {
  children: React.ReactNode
}

/**
 * Global chrome rendered once around every route: a full-width header with the product name and,
 * for a signed-in user, the account menu. Pages render only their own title and content below
 * it. Signed out, the landing card carries the brand itself, so the header stays away until
 * sign-in.
 */
export function AppShell({ children }: AppShellProps) {
  const { auth } = useAuth()

  if (auth.status === 'unauthenticated') return <>{children}</>

  return (
    <>
      <header className="app-shell__bar">
        <div className="app-shell__brand">
          <img className="app-shell__logo" src="/favicon.svg" alt="" />
          {BRAND}
        </div>
        {auth.status === 'authenticated' && <AccountMenu user={auth.user} />}
      </header>
      {children}
    </>
  )
}
