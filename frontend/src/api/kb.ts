import { apiDelete, apiGet, apiPost, apiUpload } from './client.ts'
import type { KbDocument, KbSearchResponse, KbStatus, KbUploadResult } from './types.ts'

const BASE = '/api/kb'

export async function fetchKbStatus(): Promise<KbStatus> {
  return apiGet<KbStatus>(`${BASE}/status`)
}

export async function fetchKbDocuments(): Promise<KbDocument[]> {
  return apiGet<KbDocument[]>(`${BASE}/documents`)
}

export async function uploadKbDocument(
  file: File,
  onProgress?: (fraction: number) => void,
): Promise<KbUploadResult> {
  const form = new FormData()
  form.append('file', file)
  return apiUpload<KbUploadResult>(`${BASE}/documents`, form, onProgress)
}

/**
 * Where a document's original bytes are served; opened in a new tab rather than fetched.
 *
 * A page becomes the #page fragment that browsers' built-in PDF viewers honour by convention
 * rather than by specification; a viewer that ignores it opens the document at its start.
 */
export function kbDocumentUrl(id: string, page: number | null = null): string {
  const url = `${BASE}/documents/${id}/content`
  return page === null ? url : `${url}#page=${page}`
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
