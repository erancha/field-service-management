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

/** A heading over either bullets or labelled fields; the other list is empty. */
export interface SummaryBlock {
  heading: string
  bullets: string[]
  fields: [string, string][]
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
  /** The service call's description as text. */
  problem: string
  /** The fault in one line, for a surface with one line to show. */
  headline: string
  /** The same content as blocks to render; absent unless the triage assistant escalated the call. */
  summary: SummaryBlock[] | null
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
  /** When the user accepted the assistant disclaimer; null until they have. */
  assist_disclaimer_accepted_at: string | null
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

export type PhotoVariant = 'original' | 'preview'

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

/** Offsets bounding the yes/no question inside the reply text, as the assistant delimited it. */
export interface QuestionSpan {
  start: number
  end: number
}

export interface TriageTurnResult {
  status: TriageStatus
  /**
   * Where the turn's plain yes/no question sits, or null when it asked none. Its presence is what
   * puts the Yes/No buttons up, and its offsets are what emphasise the question they answer — the
   * chat never reads the reply text to work either out.
   */
  question: QuestionSpan | null
  service_call: { id: string; description: string } | null
  /**
   * Knowledge-base documents retrieval matched strongly enough to offer the customer, best match
   * first; empty when nothing uploaded covers what they asked.
   */
  sources: SourceRef[]
}

/** A knowledge-base document the customer can open, by id and by the name to show. */
export interface SourceRef {
  id: string
  filename: string
  /** The page its best-matching passage starts on; null for a document with no pages. */
  page: number | null
}
