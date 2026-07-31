import { useState } from 'react'
import type { Appointment, PhotoRef } from '../api/types.ts'
import { Button } from './Button.tsx'
import { ReschedulePicker } from './ReschedulePicker.tsx'
import { formatWhen } from '../utils/datetime.ts'
import { splitProblem } from '../utils/problemText.ts'
import { servicePhotoUrl } from '../api/scheduling.ts'

interface AppointmentCardProps {
  appointment: Appointment
  problem?: string
  technicianName?: string
  customerName?: string
  address?: string | null
  photos?: PhotoRef[]
  onReschedule?: (id: string, start: string, end: string) => void | Promise<void>
  onCancel?: (id: string) => void
  onAddDetails?: (id: string, text: string) => void
  loading?: boolean
}

export function AppointmentCard({
  appointment,
  problem,
  technicianName,
  customerName,
  address,
  photos,
  onReschedule,
  onCancel,
  onAddDetails,
  loading = false,
}: AppointmentCardProps) {
  // At most one editing surface is open at a time; while one is open the card hides its other
  // actions so a destructive Cancel Appointment never sits beside an edit form's Save.
  const [editing, setEditing] = useState<'none' | 'reschedule' | 'details' | 'confirm-cancel'>('none')
  const [detailsText, setDetailsText] = useState('')

  function handleReschedule(start: string, end: string) {
    if (onReschedule) {
      onReschedule(appointment.id, start, end)
      setEditing('none')
    }
  }

  function handleCancel() {
    if (onCancel) {
      onCancel(appointment.id)
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

  const { problem: reportedProblem, actionItems } = splitProblem(problem ?? '')

  return (
    <div className={`appointment-card appointment-card--${status}`}>
      <div className="appointment-card__header">
        <span className="appointment-card__status" title={`id: #${appointment.id.slice(0, 8)}`}>
          {status}
        </span>
      </div>
      <dl className="appointment-card__facts">
        <dt>From</dt><dd>{formatWhen(appointment.start)}</dd>
        <dt>To</dt><dd>{formatWhen(appointment.end)}</dd>
        {reportedProblem && (
          <><dt>Problem</dt><dd className="appointment-card__problem">{reportedProblem}</dd></>
        )}
        {actionItems.length > 0 && (
          <>
            <dt>Action items</dt>
            <dd>
              <ul className="appointment-card__action-items">
                {actionItems.map((item) => (<li key={item}>{item}</li>))}
              </ul>
            </dd>
          </>
        )}
        {technicianName && (<><dt>Technician</dt><dd>{technicianName}</dd></>)}
        {customerName && (<><dt>Customer</dt><dd>{customerName}</dd></>)}
        {address && (<><dt>Address</dt><dd>{address}</dd></>)}
      </dl>
      {appointment.details && (
        <p className="appointment-card__details">{appointment.details}</p>
      )}
      {photos && photos.length > 0 && (
        <ul className="appointment-card__photos">
          {photos.map((photo) => (
            <li key={photo.id}>
              <a
                href={servicePhotoUrl(appointment.service_call_id, photo.id, 'original')}
                download={photo.filename}
              >
                <img
                  src={servicePhotoUrl(appointment.service_call_id, photo.id, 'preview')}
                  alt={photo.filename}
                  loading="lazy"
                />
              </a>
            </li>
          ))}
        </ul>
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
            <Button variant="danger" onClick={() => setEditing('confirm-cancel')} loading={loading}>
              Cancel Appointment
            </Button>
          )}
        </div>
      )}

      {!isCancelled && editing === 'confirm-cancel' && onCancel && (
        <div className="appointment-card__confirm">
          <p className="appointment-card__confirm-message">
            Cancel this appointment? This can't be undone.
          </p>
          <div className="appointment-card__form-actions">
            <Button variant="danger" onClick={handleCancel} loading={loading}>
              Yes, Cancel Appointment
            </Button>
            <Button variant="secondary" onClick={() => setEditing('none')}>
              Keep Appointment
            </Button>
          </div>
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
