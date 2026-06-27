import { useState } from 'react'
import { useAppointments } from '../../hooks/useAppointments.ts'
import { AppointmentCard } from '../../components/AppointmentCard.tsx'
import { Button } from '../../components/Button.tsx'
import { ErrorBanner } from '../../components/ErrorBanner.tsx'

interface MyAppointmentsProps {
  technicianId: string
}

export function MyAppointments({ technicianId: _technicianId }: MyAppointmentsProps) {
  const appts = useAppointments()
  const [appointmentId, setAppointmentId] = useState('')
  const [lookedUp, setLookedUp] = useState(false)

  // No endpoint to list or fetch a technician's appointments exists yet, so this
  // screen cannot load one — it is a placeholder until that endpoint lands.

  function handleLookup(e: React.FormEvent) {
    e.preventDefault()
    setLookedUp(true)
  }

  return (
    <div className="my-appointments">
      <h3>My Appointments</h3>
      <p className="my-appointments__note">
        Note: A list endpoint for technician appointments is not yet available in the backend.
        You can look up a specific appointment by ID below.
      </p>
      <ErrorBanner message={appts.error} onDismiss={appts.clearError} />

      <form onSubmit={handleLookup} className="form">
        <label>
          Appointment ID:
          <input
            type="text"
            value={appointmentId}
            onChange={(e) => setAppointmentId(e.target.value)}
            placeholder="xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx"
          />
        </label>
        <Button type="submit" disabled={!appointmentId.trim()}>
          Look Up
        </Button>
      </form>

      {lookedUp && !appts.appointment && (
        <p>Enter an appointment ID above to load it.</p>
      )}

      {appts.appointment && (
        <AppointmentCard
          appointment={appts.appointment}
          onAddDetails={appts.addDetails}
          loading={appts.loading}
        />
      )}
    </div>
  )
}
