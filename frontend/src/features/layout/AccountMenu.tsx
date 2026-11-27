import { useEffect, useRef, useState } from 'react'
import { Link, useLocation } from 'react-router-dom'
import { logout } from '../../api/auth.ts'
import type { CurrentUser } from '../../api/types.ts'
import { Icon } from '../../components/Icon.tsx'
import { useAuth } from '../auth/authContext.ts'

interface Props {
  user: CurrentUser
}

/**
 * The header's account menu: a button that drops a floating card naming the signed-in account,
 * with the profile page and sign-out as its items. The profile item is left out while that page
 * is open. A press outside the menu or Escape closes it.
 */
export function AccountMenu({ user }: Props) {
  const [open, setOpen] = useState(false)
  const box = useRef<HTMLSpanElement>(null)
  const { refresh } = useAuth()
  const location = useLocation()

  useEffect(() => {
    if (!open) return
    const dismiss = (event: MouseEvent) => {
      if (!box.current?.contains(event.target as Node)) setOpen(false)
    }
    const onEscape = (event: KeyboardEvent) => {
      if (event.key === 'Escape') setOpen(false)
    }
    document.addEventListener('mousedown', dismiss)
    document.addEventListener('keydown', onEscape)
    return () => {
      document.removeEventListener('mousedown', dismiss)
      document.removeEventListener('keydown', onEscape)
    }
  }, [open])

  async function signOut() {
    setOpen(false)
    try {
      await logout()
    } finally {
      refresh()
    }
  }

  return (
    <span className="account" ref={box}>
      <button
        type="button"
        className="account-trigger"
        aria-haspopup="menu"
        aria-expanded={open}
        aria-label="Account menu"
        onClick={() => setOpen((current) => !current)}
      >
        <Icon name={open ? 'close' : 'menu'} />
      </button>
      {open && (
        <span className="account-menu">
          <span className="account-name" title="The account you signed in with">
            {user.display_name ?? user.name}
            <span className="account-email">{user.email}</span>
          </span>
          <span role="menu">
            {location.pathname !== '/profile' && (
              <Link
                to="/profile"
                role="menuitem"
                className="menu-item"
                onClick={() => setOpen(false)}
              >
                <Icon name="profile" />
                Profile
              </Link>
            )}
            <button
              type="button"
              role="menuitem"
              className="menu-item"
              title="Leave this account"
              onClick={() => void signOut()}
            >
              <Icon name="signOut" />
              Sign out
            </button>
          </span>
        </span>
      )}
    </span>
  )
}
