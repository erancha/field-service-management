import { useState } from 'react'
import type { Appointment, UpcomingAppointment } from '../../api/types.ts'
import { useUpcomingAppointments } from '../../hooks/useUpcomingAppointments.ts'
import { useAppointments } from '../../hooks/useAppointments.ts'
import { AppointmentCard } from '../../components/AppointmentCard.tsx'
import { ErrorBanner } from '../../components/ErrorBanner.tsx'
import { Button } from '../../components/Button.tsx'

interface Props {
  limit: number
  showTechnicianName: boolean
  showReschedule: boolean
}

function formatWhen(iso: string): string {
  return new Date(iso).toLocaleString([], { dateStyle: 'medium', timeStyle: 'short' })
}

function toAppointment(it: UpcomingAppointment): Appointment {
  return {
    id: it.id,
    service_call_id: it.service_call_id,
    technician_id: it.technician_id,
    customer_id: it.customer_id,
    start: it.start,
    end: it.end,
    status: it.status,
    details: it.details ?? undefined,
  }
}

/**
 * Compact "what's next" list for a role's dashboard.
 *
 * Rows stay to two lines and live-refresh through useUpcomingAppointments. Open expands the row
 * into the shared AppointmentCard; the customer view additionally wires reschedule and add-details,
 * refetching the list after either so the shown times stay authoritative.
 */
export function UpcomingAppointments({ limit, showTechnicianName, showReschedule }: Props) {
  const { items, loading, error, refetch } = useUpcomingAppointments(limit)
  const { reschedule, addDetails, loading: mutating } = useAppointments()
  const [openId, setOpenId] = useState<string | null>(null)

  return (
    <section className="upcoming">
      <h3>Upcoming appointments</h3>
      <ErrorBanner message={error} />
      {loading && items.length === 0 ? (
        <p className="upcoming__empty">Loading…</p>
      ) : items.length === 0 ? (
        <p className="upcoming__empty">No upcoming appointments.</p>
      ) : (
        <ul className="upcoming__list">
          {items.map((it) => (
            <li key={it.id} className="upcoming__item">
              <div className="upcoming__row">
                <div className="upcoming__summary">
                  <span className="upcoming__line">
                    <span className="upcoming__when">{formatWhen(it.start)}</span>
                    <span className="upcoming__problem">{it.problem}</span>
                  </span>
                  <span className="upcoming__line upcoming__meta">
                    <span>{it.customer_name}</span>
                    {showTechnicianName && <span>{it.technician_name}</span>}
                    <span className="upcoming__address">{it.address ?? '—'}</span>
                  </span>
                </div>
                <Button
                  variant="secondary"
                  onClick={() => setOpenId(openId === it.id ? null : it.id)}
                >
                  {openId === it.id ? 'Close' : 'Open'}
                </Button>
              </div>
              {openId === it.id && (
                <AppointmentCard
                  appointment={toAppointment(it)}
                  problem={it.problem}
                  technicianName={showTechnicianName ? it.technician_name : undefined}
                  customerName={it.customer_name}
                  address={it.address}
                  loading={mutating}
                  onReschedule={
                    showReschedule
                      ? async (id, start, end) => {
                          await reschedule(id, { start, end })
                          setOpenId(null)
                          await refetch()
                        }
                      : undefined
                  }
                  onAddDetails={
                    showReschedule
                      ? async (id, text) => {
                          await addDetails(id, text)
                          await refetch()
                        }
                      : undefined
                  }
                />
              )}
            </li>
          ))}
        </ul>
      )}
    </section>
  )
}
