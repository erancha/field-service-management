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
import { useEventStream } from '../../hooks/useEventStream.ts'
import { formatWhen } from '../../utils/datetime.ts'
import { errorMessage } from '../../utils/errors.ts'

const formatSeconds = (s: number) => `${s.toFixed(1)} s`

/**
 * Back-office panel for managing the triage assistant's knowledge base.
 *
 * Lets an admin upload and delete source documents, trigger a re-index when the configured
 * embedding model no longer matches the index, and run a test search to preview which passages
 * a customer question would surface — before any chat depends on it. Renders as a disabled note
 * when the backend has no knowledge base configured.
 *
 * An upload is reported in stages, because no single source covers the whole wait: the browser
 * measures the byte transfer, then the server's ingest events carry page counts while extracting
 * and chunk counts while indexing; an indeterminate moment covers only the gap before the first
 * server event arrives. When the upload completes, a summary line splits the round trip into
 * network, extract, and index time — the server reports its two phases, and network is the
 * remainder.
 */
export function KnowledgeBasePanel() {
  const [status, setStatus] = useState<KbStatus | null>(null)
  const [documents, setDocuments] = useState<KbDocument[]>([])
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [query, setQuery] = useState('')
  const [hits, setHits] = useState<KbSearchHit[] | null>(null)
  // The document list folds away like the customer page's past conversations, so a growing
  // library cannot crowd the other panels off the shared landing page.
  const [documentsExpanded, setDocumentsExpanded] = useState(false)
  // Fraction of the upload body delivered, or null when no upload is in flight. At 1 the bytes are
  // sent and the server has taken over, extracting and then indexing.
  const [uploadFraction, setUploadFraction] = useState<number | null>(null)
  // Latest server-side ingest report — pages read while extracting, chunks written while
  // indexing — or null before the first event arrives.
  const [serverProgress, setServerProgress] = useState<{
    phase: 'extracting' | 'indexing'
    done: number
    total: number
  } | null>(null)
  // Wall-clock split of the last completed upload, shown until the next upload starts or a
  // document is deleted. Network time is the remainder of the round trip after the server's
  // own phases.
  const [summary, setSummary] = useState<{
    total: number
    extract: number
    index: number
  } | null>(null)

  useEventStream({
    'kb.ingest.progress': (data) => {
      const { phase, done, total } = data as {
        phase: 'extracting' | 'indexing'
        done: number
        total: number
      }
      setServerProgress({ phase, done, total })
    },
  })

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
    if (!file) return
    setUploadFraction(0)
    setServerProgress(null)
    setSummary(null)
    const startedAt = performance.now()
    try {
      await run(async () => {
        const result = await uploadKbDocument(file, setUploadFraction)
        setSummary({
          total: (performance.now() - startedAt) / 1000,
          extract: result.phase_seconds.extract,
          index: result.phase_seconds.index,
        })
      }, 'Upload failed')
    } finally {
      setUploadFraction(null)
      setServerProgress(null)
    }
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

      {uploadFraction !== null && (
        <p className="kb__progress" role="status">
          {uploadFraction < 1 ? (
            <>
              <span>Uploading — {Math.round(uploadFraction * 100)}%</span>
              <progress value={uploadFraction} max={1} />
            </>
          ) : serverProgress ? (
            <>
              <span>
                {serverProgress.phase === 'extracting'
                  ? `Extracting — ${serverProgress.done} of ${serverProgress.total} pages`
                  : `Indexing — ${serverProgress.done} of ${serverProgress.total} passages`}
              </span>
              <progress value={serverProgress.done} max={serverProgress.total} />
            </>
          ) : (
            <>
              <span>Extracting and indexing…</span>
              <progress />
            </>
          )}
        </p>
      )}

      {uploadFraction === null && summary && (
        <p className="kb__summary" role="status">
          Done in {formatSeconds(summary.total)} — network{' '}
          {formatSeconds(summary.total - summary.extract - summary.index)} | extract{' '}
          {formatSeconds(summary.extract)} | index {formatSeconds(summary.index)}
        </p>
      )}

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
        <>
          <button
            type="button"
            className="kb__documents-toggle"
            aria-expanded={documentsExpanded}
            onClick={() => setDocumentsExpanded((open) => !open)}
          >
            Documents ({documents.length})
          </button>
          {documentsExpanded && (
            <ul className="kb__list">
              {documents.map((d) => (
                <li key={d.id} className="kb__item">
                  <span>{d.filename}</span>
                  <span className="kb__meta">
                    {d.chunk_count} passages · {Math.ceil(d.size_bytes / 1024)} KB ·{' '}
                    {formatWhen(d.uploaded_at)}
                  </span>
                  <button
                    className="btn"
                    disabled={busy}
                    onClick={() => {
                      setSummary(null)
                      run(() => deleteKbDocument(d.id), 'Delete failed')
                    }}
                  >
                    Delete
                  </button>
                </li>
              ))}
            </ul>
          )}
        </>
      )}

      <form className="kb__search" onSubmit={handleSearch}>
        <label>
          Test search
          <span className="kb__search-box">
            <input
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="Ask like a customer would"
            />
            {query && (
              <button
                type="button"
                className="kb__search-clear"
                aria-label="Clear search"
                onClick={() => {
                  setQuery('')
                  setHits(null)
                }}
              >
                ×
              </button>
            )}
          </span>
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
