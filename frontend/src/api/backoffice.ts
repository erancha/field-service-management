import type { TechnicianRequest } from './types.ts'
import { apiGet, apiPost } from './client.ts'

const BASE = '/api/back-office/technician-requests'

export async function fetchTechnicianRequests(): Promise<TechnicianRequest[]> {
  return apiGet<TechnicianRequest[]>(BASE)
}

export async function approveTechnicianRequest(userId: string): Promise<void> {
  await apiPost(`${BASE}/${userId}/approve`, {})
}

export async function rejectTechnicianRequest(userId: string): Promise<void> {
  await apiPost(`${BASE}/${userId}/reject`, {})
}
