import { useState } from 'react'
import type { Appointment } from '../api/types.ts'
import { Button } from './Button.tsx'

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
  const [newStart, setNewStart] = useState('')
  const [newEnd, setNewEnd] = useState('')
  const [detailsText, setDetailsText] = useState('')
  const [showDetails, setShowDetails] = useState(false)

  function handleReschedule() {
    if (onReschedule && newStart && newEnd) {
      onReschedule(appointment.id, newStart, newEnd)
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
                <div className="appointment-card__reschedule">
                  <label>
                    New start:
                    <input type="datetime-local" value={newStart} onChange={(e) => setNewStart(e.target.value)} />
                  </label>
                  <label>
                    New end:
                    <input type="datetime-local" value={newEnd} onChange={(e) => setNewEnd(e.target.value)} />
                  </label>
                  <Button onClick={handleReschedule} disabled={!newStart || !newEnd} loading={loading}>
                    Confirm
                  </Button>
                </div>
              )}
            </>
          )}
          {onAddDetails && (
            <>
              <Button variant="secondary" onClick={() => setShowDetails(!showDetails)}>
                Add Details
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
