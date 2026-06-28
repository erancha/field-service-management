import type { CalendarStatus } from './types.ts'
import { apiGet } from './client.ts'

export async function fetchCalendarStatus(): Promise<CalendarStatus> {
  return apiGet<CalendarStatus>('/calendar/status')
}
