import type { CalendarStatus } from './types.ts'
import { apiGet, apiPost } from './client.ts'

export async function fetchCalendarStatus(): Promise<CalendarStatus> {
  return apiGet<CalendarStatus>('/calendar/status')
}

export async function disconnectCalendar(): Promise<void> {
  await apiPost('/calendar/disconnect', {})
}
