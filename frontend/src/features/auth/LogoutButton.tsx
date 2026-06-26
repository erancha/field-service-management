import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { logout } from '../../api/auth.ts'
import { Button } from '../../components/Button.tsx'

export function LogoutButton() {
  const [loading, setLoading] = useState(false)
  const navigate = useNavigate()

  async function handleLogout() {
    setLoading(true)
    try {
      await logout()
    } finally {
      setLoading(false)
      navigate('/')
    }
  }

  return (
    <Button variant="secondary" onClick={handleLogout} loading={loading}>
      Sign out
    </Button>
  )
}
