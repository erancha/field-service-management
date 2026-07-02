import type {
  ServiceCall,
  CreateServiceCallRequest,
  PooledAvailabilityResponse,
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

export interface PooledAvailabilityParams {
  date_from: string
  date_to: string
  limit?: number
  slot_minutes?: number
}

export async function fetchPooledAvailability(
  params: PooledAvailabilityParams,
): Promise<PooledAvailabilityResponse> {
  const query: Record<string, string> = {
    date_from: params.date_from,
    date_to: params.date_to,
  }
  if (params.limit !== undefined) {
    query.limit = String(params.limit)
  }
  if (params.slot_minutes !== undefined) {
    query.slot_minutes = String(params.slot_minutes)
  }
  return apiGet<PooledAvailabilityResponse>('/api/availability/pool', query)
}

export interface AvailabilityParams {
  technician_id: string
  date_from: string
  date_to: string
  slot_minutes?: number
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
