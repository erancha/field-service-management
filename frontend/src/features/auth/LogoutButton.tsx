import { useState } from 'react'
import { logout } from '../../api/auth.ts'
import { useAuth } from './authContext.ts'
import { Button } from '../../components/Button.tsx'

export function LogoutButton() {
  const [loading, setLoading] = useState(false)
  const { refresh } = useAuth()

  async function handleLogout() {
    setLoading(true)
    try {
      await logout()
    } finally {
      setLoading(false)
      refresh()
    }
  }

  return (
    <Button variant="secondary" onClick={handleLogout} loading={loading}>
      Sign out
    </Button>
  )
}
