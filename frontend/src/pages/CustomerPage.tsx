import { useState } from 'react'
import type { ServiceCall } from '../api/types.ts'
import { OpenServiceCall } from '../features/customer/OpenServiceCall.tsx'
import { BookFlow } from '../features/customer/BookFlow.tsx'
import { LogoutButton } from '../features/auth/LogoutButton.tsx'

interface CustomerPageProps {
  customerId: string
  email?: string
  devMode?: boolean
}

type Phase = 'open-sc' | 'book'

export function CustomerPage({ customerId, email, devMode = false }: CustomerPageProps) {
  const [phase, setPhase] = useState<Phase>('open-sc')
  const [serviceCall, setServiceCall] = useState<ServiceCall | null>(null)

  function handleServiceCallCreated(sc: ServiceCall) {
    setServiceCall(sc)
    setPhase('book')
  }

  return (
    <div className="page">
      <header className="page__header">
        <h2>Customer Dashboard</h2>
        <div className="page__header-right">
          {email && <span className="page__email">{email}</span>}
          {devMode && <span className="badge badge--dev">Dev Mode</span>}
          {!devMode && <LogoutButton />}
        </div>
      </header>

      <p className="page__id">Customer ID: <code>{customerId}</code></p>

      {phase === 'open-sc' && (
        <OpenServiceCall customerId={customerId} onCreated={handleServiceCallCreated} />
      )}

      {phase === 'book' && serviceCall && (
        <BookFlow serviceCall={serviceCall} customerId={customerId} />
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
