import { LogoutButton } from '../auth/LogoutButton.tsx'

interface TechnicianDeclinedProps {
  email?: string
}

/**
 * Shown to a technician whose request was rejected. The path forward is the customer app, so this
 * screen directs them there; signing in on the customer host reassigns them to a customer account.
 */
export function TechnicianDeclined({ email }: TechnicianDeclinedProps) {
  return (
    <div className="page">
      <header className="page__header">
        <h2>Request declined</h2>
        <div className="page__header-right">
          {email && <span className="page__email">{email}</span>}
          <LogoutButton />
        </div>
      </header>
      <p>
        Your request for technician access was declined. To continue as a customer, sign out and sign
        in through the customer app.
      </p>
    </div>
  )
}
