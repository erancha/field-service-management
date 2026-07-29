import { useEffect, useState } from 'react'
import { fetchAssistStatus } from '../api/assist.ts'

/**
 * Whether the triage chat is configured on the backend.
 *
 * enabled stays null until the answer arrives, so the customer page can hold off rather than
 * flashing the classic form and replacing it with the chat.
 */
export function useAssistStatus(): { enabled: boolean | null } {
  const [enabled, setEnabled] = useState<boolean | null>(null)

  useEffect(() => {
    let cancelled = false
    fetchAssistStatus()
      .then((status) => { if (!cancelled) setEnabled(status.enabled) })
      .catch(() => { if (!cancelled) setEnabled(false) })
    return () => { cancelled = true }
  }, [])

  return { enabled }
}
