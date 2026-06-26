export interface ServiceCall {
  id: string
  customer_id: string
  description: string
  category: string
  status: string
  created_at: string
}

export interface TimeSlot {
  start: string
  end: string
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

export interface CurrentUser {
  user_id: string
  email: string
  role: 'customer' | 'technician' | string
}

export interface ApiError {
  detail: string
}

export interface CreateServiceCallRequest {
  customer_id: string
  description: string
  category: string
}

export interface CreateAppointmentRequest {
  service_call_id: string
  technician_id: string
  customer_id: string
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
