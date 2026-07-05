import { useCallback, useEffect, useState } from 'react'
import type { TechnicianRequest } from '../../api/types.ts'
import {
  approveTechnicianRequest,
  fetchTechnicianRequests,
  rejectTechnicianRequest,
} from '../../api/backoffice.ts'
import { useEventStream } from '../../hooks/useEventStream.ts'
import { ErrorBanner } from '../../components/ErrorBanner.tsx'
import { errorMessage } from '../../utils/errors.ts'

/**
 * Live back-office queue of technicians awaiting approval.
 *
 * Loads the pending list on mount, then keeps it current from the SSE stream: a new request is
 * prepended on technician_access.requested, and a row is removed on technician_access.withdrawn
 * (the requester signed in as a customer instead) or once approved/rejected here.
 */
export function TechnicianRequestQueue() {
  const [requests, setRequests] = useState<TechnicianRequest[]>([])
  const [error, setError] = useState<string | null>(null)
  const [busyId, setBusyId] = useState<string | null>(null)

  useEffect(() => {
    fetchTechnicianRequests()
      .then(setRequests)
      .catch((e) => setError(errorMessage(e, 'Failed to load requests')))
  }, [])

  const removeById = useCallback((userId: string) => {
    setRequests((rs) => rs.filter((r) => r.user_id !== userId))
  }, [])

  useEventStream({
    'technician_access.requested': (data) => {
      const req = data as TechnicianRequest
      setRequests((rs) =>
        rs.some((r) => r.user_id === req.user_id) ? rs : [req, ...rs],
      )
    },
    'technician_access.withdrawn': (data) => {
      removeById((data as { user_id: string }).user_id)
    },
  })

  async function decide(userId: string, approve: boolean) {
    setBusyId(userId)
    setError(null)
    try {
      await (approve ? approveTechnicianRequest(userId) : rejectTechnicianRequest(userId))
      removeById(userId)
    } catch (e) {
      setError(errorMessage(e, 'Action failed'))
    } finally {
      setBusyId(null)
    }
  }

  return (
    <section className="queue">
      <h3>Pending technician requests</h3>
      {error && <ErrorBanner message={error} />}
      {requests.length === 0 ? (
        <p className="queue__empty">No pending requests.</p>
      ) : (
        <ul className="queue__list">
          {requests.map((r) => (
            <li key={r.user_id} className="queue__item">
              <span className="queue__who">
                {r.name} <span className="queue__email">{r.email}</span>
              </span>
              <span className="queue__actions">
                <button
                  className="btn btn-primary"
                  disabled={busyId === r.user_id}
                  onClick={() => decide(r.user_id, true)}
                >
                  Approve
                </button>
                <button
                  className="btn btn-secondary"
                  disabled={busyId === r.user_id}
                  onClick={() => decide(r.user_id, false)}
                >
                  Reject
                </button>
              </span>
            </li>
          ))}
        </ul>
      )}
    </section>
  )
}
