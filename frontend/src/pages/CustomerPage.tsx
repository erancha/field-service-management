import { useState } from 'react'
import type { ServiceCall } from '../api/types.ts'
import { OpenServiceCall } from '../features/customer/OpenServiceCall.tsx'
import { BookFlow } from '../features/customer/BookFlow.tsx'
import { PageHeader } from '../features/layout/PageHeader.tsx'
import { UpcomingAppointments } from '../features/appointments/UpcomingAppointments.tsx'

interface CustomerPageProps {
  customerId: string
  email?: string
}

type Phase = 'open-sc' | 'book'

export function CustomerPage({ customerId, email }: CustomerPageProps) {
  const [phase, setPhase] = useState<Phase>('open-sc')
  const [serviceCall, setServiceCall] = useState<ServiceCall | null>(null)

  function handleServiceCallCreated(sc: ServiceCall) {
    setServiceCall(sc)
    setPhase('book')
  }

  return (
    <div className="page">
      <PageHeader title="Customer Dashboard" email={email} />

      <UpcomingAppointments limit={3} showTechnicianName showReschedule />
      <p className="page__id">Customer ID: <code>{customerId}</code></p>

      {phase === 'open-sc' && (
        <OpenServiceCall onCreated={handleServiceCallCreated} />
      )}

      {phase === 'book' && serviceCall && (
        <BookFlow serviceCall={serviceCall} />
      )}

      {phase === 'book' && serviceCall && (
        <div className="page__nav">
          <button
            className="btn btn-secondary"
            onClick={() => { setPhase('open-sc'); setServiceCall(null) }}
          >
            Open another service call
          </button>
        </div>
      )}
    </div>
  )
}
