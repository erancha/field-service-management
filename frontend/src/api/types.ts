export interface ServiceCall {
  id: string
  customer_id: string
  description: string
  status: string
  created_at: string
}

export interface TimeSlot {
  start: string
  end: string
}

export interface PooledSlot extends TimeSlot {
  technician_id: string
  technician_name: string
}

export interface PooledAvailabilityResponse {
  slots: PooledSlot[]
}

export interface AvailabilityResponse {
  slots: TimeSlot[]
}

export interface Appointment {
  id: string
  service_call_id: string
  technician_id: string
  customer_id: string
  start: string
  end: string
  status: string
  details?: string
}

export type Role = 'CUSTOMER' | 'TECHNICIAN' | 'ADMIN'
export type RoleStatus = 'PENDING' | 'APPROVED' | 'REJECTED'

export interface CurrentUser {
  user_id: string
  email: string
  role: Role | string
  role_status: RoleStatus | string
  name: string
  display_name: string | null
  address: string | null
  phone: string | null
}

export interface ProfileUpdate {
  display_name?: string
  address?: string
  phone?: string
}

export interface CalendarStatus {
  connected: boolean
  fsm_calendar_id: string | null
}

export interface TechnicianRequest {
  user_id: string
  email: string
  name: string
}

export interface ApiError {
  detail: string
}

export interface CreateServiceCallRequest {
  description: string
}

export interface CreateAppointmentRequest {
  service_call_id: string
  technician_id: string
  start: string
  end: string
}

export interface RescheduleRequest {
  start: string
  end: string
}

export interface AddDetailsRequest {
  text: string
}
