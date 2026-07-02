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
  // At most one editing surface is open at a time; while one is open the card hides its other
  // actions so a destructive Cancel Appointment never sits beside an edit form's Save.
  const [editing, setEditing] = useState<'none' | 'reschedule' | 'details'>('none')
  const [detailsText, setDetailsText] = useState('')

  function handleReschedule(start: string, end: string) {
    if (onReschedule) {
      onReschedule(appointment.id, start, end)
      setEditing('none')
    }
  }

  function handleAddDetails() {
    if (onAddDetails && detailsText.trim()) {
      onAddDetails(appointment.id, detailsText.trim())
      setDetailsText('')
      setEditing('none')
    }
  }

  // Saving sends the full text as the appointment's details, so editing must start from the
  // current details — an empty form would silently discard them on save.
  function openDetailsForm() {
    setDetailsText(appointment.details ?? '')
    setEditing('details')
  }

  // The API serializes statuses uppercase (SCHEDULED/RESCHEDULED/CANCELLED); the CSS modifier
  // classes are lowercase, so all status handling goes through this normalized value.
  const status = appointment.status.toLowerCase()
  const isCancelled = status === 'cancelled'

  return (
    <div className={`appointment-card appointment-card--${status}`}>
      <div className="appointment-card__header">
        <span className="appointment-card__status">{status}</span>
        <span className="appointment-card__id">#{appointment.id.slice(0, 8)}</span>
      </div>
      <div className="appointment-card__times">
        <span>From: {formatDate(appointment.start)}</span>
        <span>To: {formatDate(appointment.end)}</span>
      </div>
      {appointment.details && (
        <p className="appointment-card__details">{appointment.details}</p>
      )}
      {!isCancelled && editing === 'none' && (
        <div className="appointment-card__actions">
          {onReschedule && (
            <Button variant="secondary" onClick={() => setEditing('reschedule')} loading={loading}>
              Reschedule
            </Button>
          )}
          {onAddDetails && (
            <Button variant="secondary" onClick={openDetailsForm}>
              {appointment.details ? 'Edit Details' : 'Add Details'}
            </Button>
          )}
          {onCancel && (
            <Button variant="danger" onClick={() => onCancel(appointment.id)} loading={loading}>
              Cancel Appointment
            </Button>
          )}
        </div>
      )}

      {!isCancelled && editing === 'reschedule' && onReschedule && (
        <div className="appointment-card__edit">
          <ReschedulePicker
            technicianId={appointment.technician_id}
            onConfirm={handleReschedule}
            loading={loading}
          />
          <Button variant="secondary" onClick={() => setEditing('none')}>
            Cancel
          </Button>
        </div>
      )}

      {!isCancelled && editing === 'details' && onAddDetails && (
        <div className="appointment-card__details-form">
          <textarea
            value={detailsText}
            onChange={(e) => setDetailsText(e.target.value)}
            placeholder="Enter appointment details…"
            rows={3}
          />
          <div className="appointment-card__form-actions">
            <Button onClick={handleAddDetails} disabled={!detailsText.trim()} loading={loading}>
              Save
            </Button>
            <Button variant="secondary" onClick={() => setEditing('none')}>
              Cancel
            </Button>
          </div>
        </div>
      )}
    </div>
  )
}
