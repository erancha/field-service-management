import { useEventStream } from '../../hooks/useEventStream.ts'
import { PageHeader } from '../layout/PageHeader.tsx'

interface TechnicianWaitingProps {
  userId: string
  onDecided: () => void
}

/**
 * Shown to a technician whose request is pending. Listens for the live approval/rejection of this
 * user and asks the parent to re-resolve the current user so the view flips to the dashboard or the
 * declined screen without a manual refresh.
 */
export function TechnicianWaiting({ userId, onDecided }: TechnicianWaitingProps) {
  useEventStream({
    'technician_access.decided': (data) => {
      if ((data as { user_id?: string }).user_id === userId) onDecided()
    },
  })

  return (
    <div className="page">
      <PageHeader title="Awaiting approval" />
      <p>
        Your request for technician access is pending review by the back office. This screen updates
        automatically once a decision is made.
      </p>
    </div>
  )
}
