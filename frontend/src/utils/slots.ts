// The booking and reschedule flows both offer slots over the same upcoming window.
export const SEARCH_DAYS = 7

export function isoDate(d: Date): string {
  const month = String(d.getMonth() + 1).padStart(2, '0')
  const day = String(d.getDate()).padStart(2, '0')
  return `${d.getFullYear()}-${month}-${day}`
}

export function searchWindow(): { date_from: string; date_to: string } {
  const from = new Date()
  const to = new Date()
  to.setDate(to.getDate() + (SEARCH_DAYS - 1))
  return { date_from: isoDate(from), date_to: isoDate(to) }
}

export function formatSlotRange(startIso: string, endIso: string): string {
  const start = new Date(startIso)
  const end = new Date(endIso)
  return `${start.toLocaleDateString()} ${start.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })} – ${end.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}`
}
