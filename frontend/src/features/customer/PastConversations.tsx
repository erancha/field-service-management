import { useEffect, useState } from 'react'
import { fetchConversation, listPastConversations } from '../../api/assist.ts'
import type {
  TriageConversationSummary,
  TriageEndedStatus,
  TriageMessage,
} from '../../api/types.ts'
import { ChatTurns } from './ChatTurns.tsx'

const OUTCOME: Record<TriageEndedStatus, string> = {
  SOLVED: 'Solved',
  ESCALATED: 'Service call opened',
  ABANDONED: 'Closed',
}

interface PastConversationsProps {
  /** Changing this reloads the list; the live chat bumps it whenever a conversation ends. */
  refreshKey: number
  /** Changing this folds the section and any open transcript away; the live chat bumps it on send. */
  collapseKey: number
}

/**
 * The customer's earlier triage exchanges, collapsed until asked for.
 *
 * The list carries only a one-line summary per conversation, so a transcript is fetched the first
 * time its row is opened and kept for the rest of the visit. History is a side note to the live
 * chat: a list that cannot be loaded is reported in one line and nothing else here is blocked.
 */
export function PastConversations({ refreshKey, collapseKey }: PastConversationsProps) {
  const [summaries, setSummaries] = useState<TriageConversationSummary[]>([])
  const [listFailed, setListFailed] = useState(false)
  const [expanded, setExpanded] = useState(false)
  const [openId, setOpenId] = useState<string | null>(null)
  const [transcripts, setTranscripts] = useState<Record<string, TriageMessage[]>>({})
  const [transcriptFailed, setTranscriptFailed] = useState(false)

  useEffect(() => {
    let cancelled = false
    listPastConversations()
      .then((rows) => {
        if (cancelled) return
        setSummaries(rows)
        setListFailed(false)
      })
      .catch(() => { if (!cancelled) setListFailed(true) })
    return () => { cancelled = true }
  }, [refreshKey])

  // Fetched transcripts survive a collapse, so reopening a row after one costs no request.
  useEffect(() => {
    setExpanded(false)
    setOpenId(null)
  }, [collapseKey])

  async function toggleRow(id: string) {
    setTranscriptFailed(false)
    if (openId === id) {
      setOpenId(null)
      return
    }
    setOpenId(id)
    if (transcripts[id] !== undefined) return
    try {
      const conversation = await fetchConversation(id)
      setTranscripts((prior) => ({ ...prior, [id]: conversation.messages }))
    } catch {
      setTranscriptFailed(true)
    }
  }

  if (listFailed) {
    return <p className="chat__history-note">Could not load your past conversations.</p>
  }
  if (summaries.length === 0) return null

  return (
    <section className="chat__history">
      <button
        type="button"
        className="chat__history-toggle"
        aria-expanded={expanded}
        onClick={() => setExpanded((open) => !open)}
      >
        Past conversations ({summaries.length})
      </button>

      {expanded && (
        <ul className="chat__history-list">
          {summaries.map((summary) => (
            <li key={summary.id}>
              <button
                type="button"
                className="chat__history-row"
                aria-expanded={openId === summary.id}
                onClick={() => toggleRow(summary.id)}
              >
                <span className="chat__history-date">
                  {new Date(summary.updated_at).toLocaleDateString()}
                </span>
                <span className="chat__history-outcome">{OUTCOME[summary.status]}</span>
                <span className="chat__history-opening">{summary.opening_line}</span>
              </button>

              {openId === summary.id && transcripts[summary.id] !== undefined && (
                <ChatTurns messages={transcripts[summary.id]} />
              )}
              {openId === summary.id && transcriptFailed && (
                <p className="chat__history-note">Could not load this conversation.</p>
              )}
            </li>
          ))}
        </ul>
      )}
    </section>
  )
}
