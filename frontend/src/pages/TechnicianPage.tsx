import { ConnectCalendar } from '../features/technician/ConnectCalendar.tsx'
import { DisconnectCalendar } from '../features/technician/DisconnectCalendar.tsx'
import { MyAppointments } from '../features/technician/MyAppointments.tsx'
import { PageHeader } from '../features/layout/PageHeader.tsx'
import { useCalendarStatus } from '../hooks/useCalendarStatus.ts'

interface TechnicianPageProps {
  technicianId: string
  email?: string
}

export function TechnicianPage({ technicianId, email }: TechnicianPageProps) {
  const { state, refresh } = useCalendarStatus()

  return (
    <div className="page">
      <PageHeader title="Technician Dashboard" email={email} />

      <p className="page__id">
        Technician ID: <code>{technicianId}</code>
        {state.status === 'connected' && (
          <>
            <span className="page__calendar-connected">✓ Google Calendar connected</span>
            <DisconnectCalendar onDisconnected={refresh} />
          </>
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
