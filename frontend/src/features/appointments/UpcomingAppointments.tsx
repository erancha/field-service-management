import { useState } from 'react'
import type { Appointment, UpcomingAppointment } from '../../api/types.ts'
import { useAppointments } from '../../hooks/useAppointments.ts'
import { AppointmentCard } from '../../components/AppointmentCard.tsx'
import { ErrorBanner } from '../../components/ErrorBanner.tsx'
import { formatWhen } from '../../utils/datetime.ts'

interface Props {
  items: UpcomingAppointment[]
  loading: boolean
  error: string | null
  refetch: () => Promise<void>
  showTechnicianName: boolean
  showReschedule: boolean
  showCancel: boolean
}

const RECENT_WINDOW_MS = 24 * 60 * 60 * 1000

// An appointment counts as freshly scheduled while its booking is under a day old, cueing the
// customer to the one they just made.
function isRecentlyScheduled(createdAtIso: string): boolean {
  return Date.now() - new Date(createdAtIso).getTime() < RECENT_WINDOW_MS
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
 * Presentational over an appointment list supplied by the owning page, so that page can share the
 * same live-maintained data for its own decisions. Rows stay to two lines; a chevron toggle expands
 * a row into the shared AppointmentCard. Reschedule and add-details are wired when showReschedule
 * is set; cancel is wired independently when showCancel is set, each refetching afterward so the
 * list stays authoritative.
 */
export function UpcomingAppointments({ items, loading, error, refetch, showTechnicianName, showReschedule, showCancel }: Props) {
  const { reschedule, addDetails, cancel, loading: mutating } = useAppointments()
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
            <li
              key={it.id}
              className={`upcoming__item${isRecentlyScheduled(it.created_at) ? ' upcoming__item--recent' : ''}`}
            >
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
                <button
                  type="button"
                  className="upcoming__toggle"
                  aria-expanded={openId === it.id}
                  aria-label={openId === it.id ? 'Collapse appointment' : 'Expand appointment'}
                  onClick={() => setOpenId(openId === it.id ? null : it.id)}
                >
                  <svg className="upcoming__chevron" viewBox="0 0 16 16" width="16" height="16" aria-hidden="true">
                    <path
                      d="M4 6l4 4 4-4"
                      fill="none"
                      stroke="currentColor"
                      strokeWidth="2"
                      strokeLinecap="round"
                      strokeLinejoin="round"
                    />
                  </svg>
                </button>
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
                  onCancel={
                    showCancel
                      ? async (id) => {
                          await cancel(id)
                          setOpenId(null)
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
