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

export interface UpcomingAppointment {
  id: string
  service_call_id: string
  technician_id: string
  customer_id: string
  start: string
  end: string
  status: string
  details: string | null
  problem: string
  technician_name: string
  customer_name: string
  address: string | null
  created_at: string
  photos: PhotoRef[]
}

export interface UpcomingAppointmentsResponse {
  items: UpcomingAppointment[]
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

export interface KbStatus {
  enabled: boolean
  embedding_model: string | null
  needs_reindex: boolean
}

export interface KbDocument {
  id: string
  filename: string
  size_bytes: number
  uploaded_at: string
  chunk_count: number
}

/** Upload response: the stored document plus how long that run's server phases took. */
export interface KbUploadResult extends KbDocument {
  phase_seconds: { extract: number; index: number }
}

export interface KbSearchHit {
  document_id: string
  filename: string
  content: string
  score: number
}

export interface KbSearchResponse {
  hits: KbSearchHit[]
}

export interface AssistStatus {
  enabled: boolean
}

export type TriageStatus = 'ACTIVE' | 'SOLVED' | 'ESCALATED' | 'ABANDONED'

/** Photo metadata shared by chat turns and the appointment gallery; the bytes are fetched by id. */
export interface PhotoRef {
  id: string
  filename: string
  size_bytes: number
}

export interface TriageMessage {
  id: string
  role: 'CUSTOMER' | 'ASSISTANT'
  text: string
  created_at: string
  photos?: PhotoRef[]
}

export interface TriageConversation {
  id: string
  status: TriageStatus
  service_call_id: string | null
  messages: TriageMessage[]
  pending_photos: PhotoRef[]
}

/** How a conversation finished. Only ended conversations enter the customer's history. */
export type TriageEndedStatus = Exclude<TriageStatus, 'ACTIVE'>

/** One row of the customer's chat history; the transcript is fetched separately, by id. */
export interface TriageConversationSummary {
  id: string
  status: TriageEndedStatus
  updated_at: string
  opening_line: string
}

export interface TriageTurnResult {
  status: TriageStatus
  service_call: { id: string; description: string } | null
}
