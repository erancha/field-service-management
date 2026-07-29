import { useCallback, useEffect, useState } from 'react'
import { ErrorBanner } from '../../components/ErrorBanner.tsx'
import {
  deleteKbDocument,
  fetchKbDocuments,
  fetchKbStatus,
  reindexKb,
  searchKb,
  uploadKbDocument,
} from '../../api/kb.ts'
import type { KbDocument, KbSearchHit, KbStatus } from '../../api/types.ts'
import { errorMessage } from '../../utils/errors.ts'

/**
 * Back-office panel for managing the triage assistant's knowledge base.
 *
 * Lets an admin upload and delete source documents, trigger a re-index when the configured
 * embedding model no longer matches the index, and run a test search to preview which passages
 * a customer question would surface — before any chat depends on it. Renders as a disabled note
 * when the backend has no knowledge base configured.
 */
export function KnowledgeBasePanel() {
  const [status, setStatus] = useState<KbStatus | null>(null)
  const [documents, setDocuments] = useState<KbDocument[]>([])
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [query, setQuery] = useState('')
  const [hits, setHits] = useState<KbSearchHit[] | null>(null)

  const refresh = useCallback(async () => {
    const s = await fetchKbStatus()
    setStatus(s)
    if (s.enabled) setDocuments(await fetchKbDocuments())
  }, [])

  useEffect(() => {
    refresh().catch((e) => setError(errorMessage(e, 'Failed to load the knowledge base')))
  }, [refresh])

  async function run(action: () => Promise<unknown>, fallback: string) {
    setBusy(true)
    setError(null)
    setHits(null)
    try {
      await action()
      await refresh()
    } catch (e) {
      setError(errorMessage(e, fallback))
    } finally {
      setBusy(false)
    }
  }

  async function handleUpload(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0]
    e.target.value = ''
    if (file) await run(() => uploadKbDocument(file), 'Upload failed')
  }

  async function handleSearch(e: React.FormEvent) {
    e.preventDefault()
    setError(null)
    try {
      setHits((await searchKb(query)).hits)
    } catch (err) {
      setError(errorMessage(err, 'Search failed'))
    }
  }

  if (status && !status.enabled) {
    return (
      <section className="kb">
        <h3>Knowledge base</h3>
        <p className="kb__disabled">
          Not configured — set the assistant keys in backend/.env to enable document search.
        </p>
      </section>
    )
  }

  return (
    <section className="kb">
      <h3>Knowledge base</h3>
      <ErrorBanner message={error} />

      <label className="kb__upload">
        Upload document
        <input type="file" accept=".pdf,.md,.txt" onChange={handleUpload} disabled={busy} />
      </label>

      {status?.needs_reindex && (
        <p className="kb__reindex">
          The embedding model changed — search is paused until documents are re-indexed.{' '}
          <button
            className="btn btn-primary"
            disabled={busy}
            onClick={() => run(() => reindexKb(), 'Re-index failed')}
          >
            Re-index now
          </button>
        </p>
      )}

      {documents.length === 0 ? (
        <p className="kb__empty">No documents uploaded yet.</p>
      ) : (
        <ul className="kb__list">
          {documents.map((d) => (
            <li key={d.id} className="kb__item">
              <span>{d.filename}</span>
              <span className="kb__meta">
                {d.chunk_count} passages · {Math.ceil(d.size_bytes / 1024)} KB
              </span>
              <button
                className="btn"
                disabled={busy}
                onClick={() => run(() => deleteKbDocument(d.id), 'Delete failed')}
              >
                Delete
              </button>
            </li>
          ))}
        </ul>
      )}

      <form className="kb__search" onSubmit={handleSearch}>
        <label>
          Test search
          <input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Ask like a customer would"
          />
        </label>
        <button className="btn" type="submit" disabled={!query.trim()}>
          Search
        </button>
      </form>
      {hits && (
        <ul className="kb__hits">
          {hits.length === 0 && <li className="kb__empty">No matching passages.</li>}
          {hits.map((h, i) => (
            <li key={i} className="kb__hit">
              <span className="kb__hit-source">
                {h.filename} · {Math.round(h.score * 100)}% match
              </span>
              <p>{h.content}</p>
            </li>
          ))}
        </ul>
      )}
    </section>
  )
}
