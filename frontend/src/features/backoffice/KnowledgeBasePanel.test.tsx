import { beforeEach, describe, expect, it, vi } from 'vitest'
import { act, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

vi.mock('../../api/kb.ts', () => ({
  fetchKbStatus: vi.fn(),
  fetchKbDocuments: vi.fn(),
  uploadKbDocument: vi.fn(),
  deleteKbDocument: vi.fn(),
  searchKb: vi.fn(),
  reindexKb: vi.fn(),
}))
import {
  deleteKbDocument,
  fetchKbDocuments,
  fetchKbStatus,
  searchKb,
  uploadKbDocument,
} from '../../api/kb.ts'
import { FakeEventSource } from '../../test/fakeEventSource.ts'
import { KnowledgeBasePanel } from './KnowledgeBasePanel.tsx'

const DOC = {
  id: 'd1',
  filename: 'reset-guide.md',
  size_bytes: 120,
  uploaded_at: '2026-07-28T12:00:00Z',
  chunk_count: 3,
}

// What the upload endpoint returns: the document plus that run's phase timings.
const UPLOADED = { ...DOC, phase_seconds: { extract: 3.2, index: 8.8 } }

// The document list folds away behind this count toggle; most tests only need the toggle's
// appearance as the panel-ready signal.
const findDocumentsToggle = () => screen.findByRole('button', { name: /documents \(\d+\)/i })

async function openDocuments() {
  await userEvent.click(await findDocumentsToggle())
}

describe('KnowledgeBasePanel', () => {
  beforeEach(() => {
    FakeEventSource.reset()
    vi.stubGlobal('EventSource', FakeEventSource)
    vi.mocked(fetchKbStatus).mockReset()
    vi.mocked(fetchKbDocuments).mockReset()
    vi.mocked(uploadKbDocument).mockReset()
    vi.mocked(deleteKbDocument).mockReset()
    vi.mocked(searchKb).mockReset()
    vi.mocked(fetchKbStatus).mockResolvedValue({
      enabled: true,
      embedding_model: 'openai:text-embedding-3-small',
      needs_reindex: false,
    })
    vi.mocked(fetchKbDocuments).mockResolvedValue([DOC])
  })

  it('shows the disabled note when the feature is not configured', async () => {
    vi.mocked(fetchKbStatus).mockResolvedValue({
      enabled: false,
      embedding_model: null,
      needs_reindex: false,
    })
    render(<KnowledgeBasePanel />)
    expect(await screen.findByText(/not configured/i)).toBeInTheDocument()
    expect(fetchKbDocuments).not.toHaveBeenCalled()
  })

  it('lists documents and deletes one', async () => {
    vi.mocked(deleteKbDocument).mockResolvedValue({ deleted: true })
    render(<KnowledgeBasePanel />)
    await openDocuments()
    expect(screen.getByText('reset-guide.md')).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: /delete/i }))
    expect(deleteKbDocument).toHaveBeenCalledWith('d1')
  })

  it('uploads the chosen file and refreshes the list', async () => {
    vi.mocked(uploadKbDocument).mockResolvedValue(UPLOADED)
    render(<KnowledgeBasePanel />)
    await findDocumentsToggle()
    const file = new File(['# hi'], 'new.md', { type: 'text/markdown' })
    await userEvent.upload(screen.getByLabelText(/upload document/i), file)
    expect(uploadKbDocument).toHaveBeenCalledWith(file, expect.any(Function))
  })

  it('shows transfer percentage, then an indeterminate indexing phase, then clears', async () => {
    let reportProgress: ((fraction: number) => void) | undefined
    let finishUpload: ((doc: typeof UPLOADED) => void) | undefined
    vi.mocked(uploadKbDocument).mockImplementation((_file, onProgress) => {
      reportProgress = onProgress
      return new Promise((resolve) => {
        finishUpload = resolve
      })
    })
    render(<KnowledgeBasePanel />)
    await findDocumentsToggle()
    const file = new File(['# hi'], 'new.md', { type: 'text/markdown' })
    await userEvent.upload(screen.getByLabelText(/upload document/i), file)

    act(() => reportProgress!(0.42))
    expect(screen.getByText(/uploading — 42%/i)).toBeInTheDocument()

    act(() => reportProgress!(1))
    expect(screen.getByText(/extracting and indexing/i)).toBeInTheDocument()

    await act(async () => finishUpload!(UPLOADED))
    expect(screen.queryByText(/extracting and indexing/i)).not.toBeInTheDocument()
    expect(screen.queryByText(/uploading —/i)).not.toBeInTheDocument()
  })

  it('shows a timing summary once the upload completes, until the next upload starts', async () => {
    vi.mocked(uploadKbDocument).mockResolvedValue(UPLOADED)
    render(<KnowledgeBasePanel />)
    await findDocumentsToggle()
    const file = new File(['# hi'], 'new.md', { type: 'text/markdown' })
    await userEvent.upload(screen.getByLabelText(/upload document/i), file)

    const summary = await screen.findByText(/extract 3\.2 s \| index 8\.8 s/i)
    // Total and network come from the panel's own clock; the mocked request resolves in ~0 ms,
    // so only their shape is asserted.
    expect(summary.textContent).toMatch(
      /^Done in .+ — network .+ \| extract 3\.2 s \| index 8\.8 s$/,
    )

    vi.mocked(uploadKbDocument).mockImplementation(() => new Promise(() => {}))
    await userEvent.upload(
      screen.getByLabelText(/upload document/i),
      new File(['x'], 'again.md', { type: 'text/markdown' }),
    )
    expect(screen.queryByText(/extract 3\.2 s/i)).not.toBeInTheDocument()
  })

  it('removes the timing summary when a document is deleted', async () => {
    vi.mocked(uploadKbDocument).mockResolvedValue(UPLOADED)
    vi.mocked(deleteKbDocument).mockResolvedValue({ deleted: true })
    render(<KnowledgeBasePanel />)
    await openDocuments()
    const file = new File(['# hi'], 'new.md', { type: 'text/markdown' })
    await userEvent.upload(screen.getByLabelText(/upload document/i), file)
    expect(await screen.findByText(/extract 3\.2 s/i)).toBeInTheDocument()

    await userEvent.click(screen.getByRole('button', { name: /delete/i }))
    expect(screen.queryByText(/extract 3\.2 s/i)).not.toBeInTheDocument()
  })

  it('replaces the indeterminate phase with per-page extraction, then chunk indexing counts', async () => {
    let reportProgress: ((fraction: number) => void) | undefined
    vi.mocked(uploadKbDocument).mockImplementation((_file, onProgress) => {
      reportProgress = onProgress
      return new Promise(() => {}) // still ingesting when the assertions run
    })
    render(<KnowledgeBasePanel />)
    await findDocumentsToggle()
    const file = new File(['x'], 'manual.pdf', { type: 'application/pdf' })
    await userEvent.upload(screen.getByLabelText(/upload document/i), file)

    act(() => reportProgress!(1))
    expect(screen.getByText(/extracting and indexing/i)).toBeInTheDocument()

    act(() => FakeEventSource.last().emit('kb.ingest.progress', {
      filename: 'manual.pdf',
      phase: 'extracting',
      done: 137,
      total: 414,
    }))

    expect(screen.getByText(/extracting — 137 of 414 pages/i)).toBeInTheDocument()
    expect(screen.queryByText(/extracting and indexing/i)).not.toBeInTheDocument()

    act(() => FakeEventSource.last().emit('kb.ingest.progress', {
      filename: 'manual.pdf',
      phase: 'indexing',
      done: 64,
      total: 1007,
    }))

    expect(screen.getByText(/indexing — 64 of 1007 passages/i)).toBeInTheDocument()
    expect(screen.queryByText(/extracting — 137/i)).not.toBeInTheDocument()
  })

  it('runs a test search and shows matching passages', async () => {
    vi.mocked(searchKb).mockResolvedValue({
      hits: [{ document_id: 'd1', filename: 'reset-guide.md', content: 'Hold the button', score: 0.87 }],
    })
    render(<KnowledgeBasePanel />)
    await findDocumentsToggle()
    await userEvent.type(screen.getByLabelText(/test search/i), 'reset')
    await userEvent.click(screen.getByRole('button', { name: /^search$/i }))
    expect(await screen.findByText(/hold the button/i)).toBeInTheDocument()
    expect(screen.getByText(/87% match/i)).toBeInTheDocument()
  })

  it('clears stale search results once the document set changes', async () => {
    vi.mocked(searchKb).mockResolvedValue({
      hits: [{ document_id: 'd1', filename: 'reset-guide.md', content: 'Hold the button', score: 0.87 }],
    })
    vi.mocked(deleteKbDocument).mockResolvedValue({ deleted: true })
    render(<KnowledgeBasePanel />)
    await openDocuments()
    await userEvent.type(screen.getByLabelText(/test search/i), 'reset')
    await userEvent.click(screen.getByRole('button', { name: /^search$/i }))
    expect(await screen.findByText(/hold the button/i)).toBeInTheDocument()

    vi.mocked(fetchKbDocuments).mockResolvedValue([])
    await userEvent.click(screen.getByRole('button', { name: /delete/i }))

    expect(await screen.findByText(/no documents uploaded yet/i)).toBeInTheDocument()
    expect(screen.queryByText(/hold the button/i)).not.toBeInTheDocument()
  })

  it('folds the document list behind a count toggle, collapsed until asked for', async () => {
    const docs = Array.from({ length: 7 }, (_, i) => ({
      ...DOC,
      id: `d${i + 1}`,
      filename: `doc-${i + 1}.md`,
    }))
    vi.mocked(fetchKbDocuments).mockResolvedValue(docs)
    render(<KnowledgeBasePanel />)
    const toggle = await screen.findByRole('button', { name: /documents \(7\)/i })
    expect(screen.queryByText('doc-1.md')).not.toBeInTheDocument()

    await userEvent.click(toggle)
    expect(screen.getByText('doc-1.md')).toBeInTheDocument()
    expect(screen.getByText('doc-7.md')).toBeInTheDocument()

    await userEvent.click(toggle)
    expect(screen.queryByText('doc-1.md')).not.toBeInTheDocument()
  })

  it('clears the test-search box and its results with the clear button', async () => {
    vi.mocked(searchKb).mockResolvedValue({
      hits: [{ document_id: 'd1', filename: 'reset-guide.md', content: 'Hold the button', score: 0.87 }],
    })
    render(<KnowledgeBasePanel />)
    await findDocumentsToggle()
    expect(screen.queryByRole('button', { name: /clear search/i })).not.toBeInTheDocument()

    const input = screen.getByLabelText(/test search/i)
    await userEvent.type(input, 'reset')
    await userEvent.click(screen.getByRole('button', { name: /^search$/i }))
    expect(await screen.findByText(/hold the button/i)).toBeInTheDocument()

    await userEvent.click(screen.getByRole('button', { name: /clear search/i }))
    expect(input).toHaveValue('')
    expect(screen.queryByText(/hold the button/i)).not.toBeInTheDocument()
  })

  it('surfaces an upload error', async () => {
    vi.mocked(uploadKbDocument).mockRejectedValue(new Error('too large'))
    render(<KnowledgeBasePanel />)
    await findDocumentsToggle()
    const file = new File(['x'], 'big.txt', { type: 'text/plain' })
    await userEvent.upload(screen.getByLabelText(/upload document/i), file)
    expect(await screen.findByRole('alert')).toBeInTheDocument()
  })
})
