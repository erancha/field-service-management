import { ConnectCalendar } from '../features/technician/ConnectCalendar.tsx'
import { DisconnectCalendar } from '../features/technician/DisconnectCalendar.tsx'
import { PageHeader } from '../features/layout/PageHeader.tsx'
import { UpcomingAppointments } from '../features/appointments/UpcomingAppointments.tsx'
import { useCalendarStatus } from '../hooks/useCalendarStatus.ts'
import { useUpcomingAppointments } from '../hooks/useUpcomingAppointments.ts'

interface TechnicianPageProps {
  technicianId: string
  email?: string
}

const GOOGLE_CALENDAR_URL = 'https://calendar.google.com/calendar/'

export function TechnicianPage({ technicianId, email }: TechnicianPageProps) {
  const { state, refresh } = useCalendarStatus()
  const upcoming = useUpcomingAppointments(5, state.status === 'connected')

  return (
    <div className="page">
      <PageHeader title="Technician Dashboard" email={email} accountId={technicianId} />

      {state.status === 'connected' && (
        <p className="page__calendar-status">
          <a
            className="page__calendar-connected"
            href={GOOGLE_CALENDAR_URL}
            target="_blank"
            rel="noopener noreferrer"
          >
            ✓ Google Calendar connected
          </a>
          <DisconnectCalendar onDisconnected={refresh} />
        </p>
      )}

      {state.status === 'connected' ? (
        <UpcomingAppointments
          items={upcoming.items}
          loading={upcoming.loading}
          error={upcoming.error}
          refetch={upcoming.refetch}
          showTechnicianName={false}
          showReschedule={false}
          showCancel
        />
      ) : (
        <ConnectCalendar status={state.status} />
      )}
    </div>
  )
}
