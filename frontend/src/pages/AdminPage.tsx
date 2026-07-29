import { PageHeader } from '../features/layout/PageHeader.tsx'
import { TechnicianRequestQueue } from '../features/backoffice/TechnicianRequestQueue.tsx'
import { KnowledgeBasePanel } from '../features/backoffice/KnowledgeBasePanel.tsx'
import { UpcomingAppointments } from '../features/appointments/UpcomingAppointments.tsx'
import { useUpcomingAppointments } from '../hooks/useUpcomingAppointments.ts'

interface AdminPageProps {
  email?: string
}

export function AdminPage({ email }: AdminPageProps) {
  const upcoming = useUpcomingAppointments(10)

  return (
    <div className="page">
      <PageHeader title="Back office" email={email} />

      <UpcomingAppointments
        items={upcoming.items}
        loading={upcoming.loading}
        error={upcoming.error}
        refetch={upcoming.refetch}
        showTechnicianName
        showReschedule={false}
        showCancel={false}
      />
      <TechnicianRequestQueue />
      <KnowledgeBasePanel />
    </div>
  )
}
