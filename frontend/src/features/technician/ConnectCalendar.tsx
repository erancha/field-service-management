import { ErrorBanner } from '../../components/ErrorBanner.tsx'
import { useCalendarConnectError } from '../../hooks/useCalendarConnectError.ts'

type ConnectionStatus = 'loading' | 'connected' | 'disconnected'

interface ConnectCalendarProps {
  status: ConnectionStatus
}

const CONNECT_DENIED_MESSAGE =
  "Google Calendar wasn't connected — the calendar permissions weren't granted. " +
  'Please try again and allow calendar access when Google asks.'

export function ConnectCalendar({ status }: ConnectCalendarProps) {
  const { rejected, dismiss } = useCalendarConnectError()
  return (
    <div className="connect-calendar">
      <h3>Google Calendar Integration</h3>
      {rejected && <ErrorBanner message={CONNECT_DENIED_MESSAGE} onDismiss={dismiss} />}
      {status === 'loading' && (
        <p className="connect-calendar__checking">Checking calendar connection…</p>
      )}
      {status === 'connected' && (
        <p className="connect-calendar__status">
          ✓ Your Google Calendar is connected. Appointments are scheduled against your real
          availability.
        </p>
      )}
      {status === 'disconnected' && (
        <>
          <p>
            Connect your Google Calendar to allow appointment scheduling against your real
            availability.
          </p>
          <a href="/calendar/connect/login" className="btn btn-primary">
            Connect Google Calendar
          </a>
        </>
      )}
    </div>
  )
}
