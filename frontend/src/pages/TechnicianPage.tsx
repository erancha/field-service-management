import { Link } from 'react-router-dom'
import { ConnectCalendar } from '../features/technician/ConnectCalendar.tsx'
import { MyAppointments } from '../features/technician/MyAppointments.tsx'
import { LogoutButton } from '../features/auth/LogoutButton.tsx'
import { useCalendarStatus } from '../hooks/useCalendarStatus.ts'

interface TechnicianPageProps {
  technicianId: string
  email?: string
}

export function TechnicianPage({ technicianId, email }: TechnicianPageProps) {
  const { state } = useCalendarStatus()

  return (
    <div className="page">
      <header className="page__header">
        <h2>Technician Dashboard</h2>
        <div className="page__header-right">
          {email && <span className="page__email">{email}</span>}
          <Link to="/profile" className="btn btn-secondary">Profile</Link>
          <LogoutButton />
        </div>
      </header>

      <p className="page__id">
        Technician ID: <code>{technicianId}</code>
        {state.status === 'connected' && (
          <span className="page__calendar-connected">✓ Google Calendar connected</span>
        )}
      </p>

      {state.status === 'connected' ? (
        <MyAppointments />
      ) : (
        <ConnectCalendar status={state.status} />
      )}
    </div>
  )
}
