import type {
  ServiceCall,
  CreateServiceCallRequest,
  AvailabilityResponse,
  Appointment,
  CreateAppointmentRequest,
  RescheduleRequest,
  AddDetailsRequest,
} from './types.ts'
import { apiPost, apiGet } from './client.ts'

export async function createServiceCall(
  data: CreateServiceCallRequest,
): Promise<ServiceCall> {
  return apiPost<ServiceCall>('/api/service-calls', data)
}

export interface AvailabilityParams {
  technician_id: string
  date_from: string
  date_to: string
  slot_minutes?: number
  tz?: string
}

export async function fetchAvailability(
  params: AvailabilityParams,
): Promise<AvailabilityResponse> {
  const query: Record<string, string> = {
    technician_id: params.technician_id,
    date_from: params.date_from,
    date_to: params.date_to,
  }
  if (params.slot_minutes !== undefined) {
    query.slot_minutes = String(params.slot_minutes)
  }
  if (params.tz) {
    query.tz = params.tz
  }
  return apiGet<AvailabilityResponse>('/api/availability', query)
}

export async function createAppointment(
  data: CreateAppointmentRequest,
): Promise<Appointment> {
  return apiPost<Appointment>('/api/appointments', data)
}

export async function rescheduleAppointment(
  id: string,
  data: RescheduleRequest,
): Promise<Appointment> {
  return apiPost<Appointment>(`/api/appointments/${id}/reschedule`, data)
}

export async function cancelAppointment(id: string): Promise<Appointment> {
  return apiPost<Appointment>(`/api/appointments/${id}/cancel`, {})
}

export async function addAppointmentDetails(
  id: string,
  data: AddDetailsRequest,
): Promise<Appointment> {
  return apiPost<Appointment>(`/api/appointments/${id}/details`, data)
}
