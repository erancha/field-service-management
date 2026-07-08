import { PageHeader } from '../features/layout/PageHeader.tsx'
import { TechnicianRequestQueue } from '../features/backoffice/TechnicianRequestQueue.tsx'
import { UpcomingAppointments } from '../features/appointments/UpcomingAppointments.tsx'

interface AdminPageProps {
  email?: string
}

export function AdminPage({ email }: AdminPageProps) {
  return (
    <div className="page">
      <PageHeader title="Back office" email={email} />

      <UpcomingAppointments limit={10} showTechnicianName showReschedule={false} />
      <TechnicianRequestQueue />
    </div>
  )
}
