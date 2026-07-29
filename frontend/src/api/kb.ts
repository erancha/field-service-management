import { apiDelete, apiGet, apiPost, apiUpload } from './client.ts'
import type { KbDocument, KbSearchResponse, KbStatus } from './types.ts'

const BASE = '/api/kb'

export async function fetchKbStatus(): Promise<KbStatus> {
  return apiGet<KbStatus>(`${BASE}/status`)
}

export async function fetchKbDocuments(): Promise<KbDocument[]> {
  return apiGet<KbDocument[]>(`${BASE}/documents`)
}

export async function uploadKbDocument(file: File): Promise<KbDocument> {
  const form = new FormData()
  form.append('file', file)
  return apiUpload<KbDocument>(`${BASE}/documents`, form)
}

export async function deleteKbDocument(id: string): Promise<{ deleted: boolean }> {
  return apiDelete<{ deleted: boolean }>(`${BASE}/documents/${id}`)
}

export async function searchKb(query: string): Promise<KbSearchResponse> {
  return apiPost<KbSearchResponse>(`${BASE}/search`, { query })
}

export async function reindexKb(): Promise<{ documents: number }> {
  return apiPost<{ documents: number }>(`${BASE}/reindex`, {})
}
