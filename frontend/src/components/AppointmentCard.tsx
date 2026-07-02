import { useState } from 'react'
import type { Appointment } from '../api/types.ts'
import { Button } from './Button.tsx'
import { ReschedulePicker } from './ReschedulePicker.tsx'

interface AppointmentCardProps {
  appointment: Appointment
  onReschedule?: (id: string, start: string, end: string) => void | Promise<void>
  onCancel?: (id: string) => void
  onAddDetails?: (id: string, text: string) => void
  loading?: boolean
}

function formatDate(iso: string): string {
  return new Date(iso).toLocaleString()
}

export function AppointmentCard({
  appointment,
  onReschedule,
  onCancel,
  onAddDetails,
  loading = false,
}: AppointmentCardProps) {
  const [showReschedule, setShowReschedule] = useState(false)
  const [detailsText, setDetailsText] = useState('')
  const [showDetails, setShowDetails] = useState(false)

  function handleReschedule(start: string, end: string) {
    if (onReschedule) {
      onReschedule(appointment.id, start, end)
      setShowReschedule(false)
    }
  }

  function handleAddDetails() {
    if (onAddDetails && detailsText.trim()) {
      onAddDetails(appointment.id, detailsText.trim())
      setDetailsText('')
      setShowDetails(false)
    }
  }

  // Saving sends the full text as the appointment's details, so editing must start from the
  // current details — an empty form would silently discard them on save.
  function toggleDetailsForm() {
    if (!showDetails) {
      setDetailsText(appointment.details ?? '')
    }
    setShowDetails(!showDetails)
  }

  const isCancelled = appointment.status === 'cancelled'

  return (
    <div className={`appointment-card appointment-card--${appointment.status}`}>
      <div className="appointment-card__header">
        <span className="appointment-card__status">{appointment.status}</span>
        <span className="appointment-card__id">#{appointment.id.slice(0, 8)}</span>
      </div>
      <div className="appointment-card__times">
        <span>From: {formatDate(appointment.start)}</span>
        <span>To: {formatDate(appointment.end)}</span>
      </div>
      {appointment.details && (
        <p className="appointment-card__details">{appointment.details}</p>
      )}
      {!isCancelled && (
        <div className="appointment-card__actions">
          {onReschedule && (
            <>
              <Button variant="secondary" onClick={() => setShowReschedule(!showReschedule)} loading={loading}>
                Reschedule
              </Button>
              {showReschedule && (
                <ReschedulePicker
                  technicianId={appointment.technician_id}
                  onConfirm={handleReschedule}
                  loading={loading}
                />
              )}
            </>
          )}
          {onAddDetails && (
            <>
              <Button variant="secondary" onClick={toggleDetailsForm}>
                {appointment.details ? 'Edit Details' : 'Add Details'}
              </Button>
              {showDetails && (
                <div className="appointment-card__details-form">
                  <textarea
                    value={detailsText}
                    onChange={(e) => setDetailsText(e.target.value)}
                    placeholder="Enter appointment details…"
                    rows={3}
                  />
                  <Button onClick={handleAddDetails} disabled={!detailsText.trim()} loading={loading}>
                    Save
                  </Button>
                </div>
              )}
            </>
          )}
          {onCancel && (
            <Button variant="danger" onClick={() => onCancel(appointment.id)} loading={loading}>
              Cancel Appointment
            </Button>
          )}
        </div>
      )}
    </div>
  )
}
