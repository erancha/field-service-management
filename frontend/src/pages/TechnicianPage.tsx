import { ConnectCalendar } from '../features/technician/ConnectCalendar.tsx'
import { MyAppointments } from '../features/technician/MyAppointments.tsx'
import { LogoutButton } from '../features/auth/LogoutButton.tsx'

interface TechnicianPageProps {
  technicianId: string
  email?: string
}

export function TechnicianPage({ technicianId, email }: TechnicianPageProps) {
  return (
    <div className="page">
      <header className="page__header">
        <h2>Technician Dashboard</h2>
        <div className="page__header-right">
          {email && <span className="page__email">{email}</span>}
          <LogoutButton />
        </div>
      </header>

      <p className="page__id">Technician ID: <code>{technicianId}</code></p>

      <ConnectCalendar />
      <MyAppointments technicianId={technicianId} />
    </div>
  )
}
