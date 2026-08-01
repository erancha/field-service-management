import { useState } from 'react'
import type { ServiceCall } from '../api/types.ts'
import { OpenServiceCall } from '../features/customer/OpenServiceCall.tsx'
import { TriageChat } from '../features/customer/TriageChat.tsx'
import { BookFlow } from '../features/customer/BookFlow.tsx'
import { PageHeader } from '../features/layout/PageHeader.tsx'
import { UpcomingAppointments } from '../features/appointments/UpcomingAppointments.tsx'
import { useUpcomingAppointments } from '../hooks/useUpcomingAppointments.ts'
import { useAssistStatus } from '../hooks/useAssistStatus.ts'

interface CustomerPageProps {
  customerId: string
}

type Phase = 'open-sc' | 'book'

const UPCOMING_LIMIT = 3

export function CustomerPage({ customerId }: CustomerPageProps) {
  const [phase, setPhase] = useState<Phase>('open-sc')
  const [serviceCall, setServiceCall] = useState<ServiceCall | null>(null)
  // assist.enabled reports startup configuration, not provider health, so a chat that cannot
  // complete a turn is the customer's only signal. Opening a service call must never depend on the
  // assistant being reachable, so giving up on the chat falls back to the classic form for the
  // rest of the visit.
  const [gaveUpOnChat, setGaveUpOnChat] = useState(false)
  const upcoming = useUpcomingAppointments(UPCOMING_LIMIT)
  const assist = useAssistStatus()

  // One customer maps to one service address, so a single open service call at a time is the only
  // meaningful state; a booked appointment blocks opening another until it is done or cancelled.
  const hasUpcoming = upcoming.items.length > 0

  function handleServiceCallCreated(sc: ServiceCall) {
    setServiceCall(sc)
    setPhase('book')
  }

  function handleBooked() {
    setPhase('open-sc')
    setServiceCall(null)
    void upcoming.refetch()
  }

  return (
    <div className="page">
      <PageHeader title="Customer Dashboard" accountId={customerId} />

      <UpcomingAppointments
        items={upcoming.items}
        loading={upcoming.loading}
        error={upcoming.error}
        refetch={upcoming.refetch}
        showTechnicianName
        showReschedule
        showCancel
      />

      {!hasUpcoming && phase === 'open-sc' && assist.enabled === true && !gaveUpOnChat && (
        <TriageChat
          onEscalated={handleServiceCallCreated}
          onGiveUp={() => setGaveUpOnChat(true)}
        />
      )}

      {!hasUpcoming && phase === 'open-sc' && (assist.enabled === false || gaveUpOnChat) && (
        <OpenServiceCall onCreated={handleServiceCallCreated} />
      )}

      {!hasUpcoming && phase === 'book' && serviceCall && (
        <>
          <BookFlow serviceCall={serviceCall} onBooked={handleBooked} />
          <div className="page__nav">
            <button
              className="btn btn-secondary"
              onClick={() => { setPhase('open-sc'); setServiceCall(null) }}
            >
              Open another service call
            </button>
          </div>
        </>
      )}
    </div>
  )
}
