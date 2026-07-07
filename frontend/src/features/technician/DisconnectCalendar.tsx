import { useState } from 'react'
import { disconnectCalendar } from '../../api/calendar.ts'

interface DisconnectCalendarProps {
  onDisconnected: () => void
}

export function DisconnectCalendar({ onDisconnected }: DisconnectCalendarProps) {
  const [confirming, setConfirming] = useState(false)
  const [pending, setPending] = useState(false)
  const [failed, setFailed] = useState(false)

  async function confirmDisconnect() {
    setPending(true)
    setFailed(false)
    try {
      await disconnectCalendar()
      onDisconnected()
    } catch {
      setFailed(true)
      setPending(false)
      setConfirming(false)
    }
  }

  if (confirming) {
    return (
      <span className="calendar-disconnect">
        <span className="calendar-disconnect__prompt">Disconnect?</span>
        <button
          type="button"
          className="calendar-disconnect__confirm"
          onClick={confirmDisconnect}
          disabled={pending}
        >
          {pending ? 'Disconnecting…' : 'Confirm'}
        </button>
        <button
          type="button"
          className="calendar-disconnect__cancel"
          onClick={() => setConfirming(false)}
          disabled={pending}
        >
          Cancel
        </button>
      </span>
    )
  }

  return (
    <span className="calendar-disconnect">
      <button
        type="button"
        className="calendar-disconnect__trigger"
        onClick={() => setConfirming(true)}
      >
        <span aria-hidden="true">🔌</span> Disconnect
      </button>
      {failed && (
        <span className="calendar-disconnect__error" role="alert">
          Couldn't disconnect. Try again.
        </span>
      )}
    </span>
  )
}
