import { PageHeader } from '../features/layout/PageHeader.tsx'
import { TechnicianRequestQueue } from '../features/backoffice/TechnicianRequestQueue.tsx'

interface AdminPageProps {
  email?: string
}

export function AdminPage({ email }: AdminPageProps) {
  return (
    <div className="page">
      <PageHeader title="Back office" email={email} />

      <TechnicianRequestQueue />
    </div>
  )
}
