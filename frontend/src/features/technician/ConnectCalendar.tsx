type ConnectionStatus = 'loading' | 'connected' | 'disconnected'

interface ConnectCalendarProps {
  status: ConnectionStatus
}

export function ConnectCalendar({ status }: ConnectCalendarProps) {
  return (
    <div className="connect-calendar">
      <h3>Google Calendar Integration</h3>
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
