import { PageHeader } from '../layout/PageHeader.tsx'

/**
 * Shown to a technician whose request was rejected. The path forward is the customer app, so this
 * screen directs them there; signing in on the customer host reassigns them to a customer account.
 */
export function TechnicianDeclined() {
  return (
    <div className="page">
      <PageHeader title="Request declined" />
      <p>
        Your request for technician access was declined. To continue as a customer, sign out and sign
        in through the customer app.
      </p>
    </div>
  )
}
