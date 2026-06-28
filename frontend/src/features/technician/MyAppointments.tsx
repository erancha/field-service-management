const GOOGLE_CALENDAR_URL = 'https://calendar.google.com/calendar/'

export function MyAppointments() {
  return (
    <div className="my-appointments">
      <h3>My Appointments</h3>
      <p className="my-appointments__note">
        Your appointments appear on the "Field Service Management" calendar in your connected Google
        Calendar. Edits you make there (reschedule, cancel, add details) are synced back into this
        system automatically.
      </p>
      <a
        href={GOOGLE_CALENDAR_URL}
        target="_blank"
        rel="noopener noreferrer"
        className="btn btn-primary"
      >
        Open Google Calendar
      </a>
    </div>
  )
}
