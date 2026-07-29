import { beforeEach, describe, expect, it, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
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
import { KnowledgeBasePanel } from './KnowledgeBasePanel.tsx'

const DOC = {
  id: 'd1',
  filename: 'reset-guide.md',
  size_bytes: 120,
  uploaded_at: '2026-07-28T12:00:00Z',
  chunk_count: 3,
}

describe('KnowledgeBasePanel', () => {
  beforeEach(() => {
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
    expect(await screen.findByText('reset-guide.md')).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: /delete/i }))
    expect(deleteKbDocument).toHaveBeenCalledWith('d1')
  })

  it('uploads the chosen file and refreshes the list', async () => {
    vi.mocked(uploadKbDocument).mockResolvedValue(DOC)
    render(<KnowledgeBasePanel />)
    await screen.findByText('reset-guide.md')
    const file = new File(['# hi'], 'new.md', { type: 'text/markdown' })
    await userEvent.upload(screen.getByLabelText(/upload document/i), file)
    expect(uploadKbDocument).toHaveBeenCalledWith(file)
  })

  it('runs a test search and shows matching passages', async () => {
    vi.mocked(searchKb).mockResolvedValue({
      hits: [{ document_id: 'd1', filename: 'reset-guide.md', content: 'Hold the button', score: 0.87 }],
    })
    render(<KnowledgeBasePanel />)
    await screen.findByText('reset-guide.md')
    await userEvent.type(screen.getByLabelText(/test search/i), 'reset')
    await userEvent.click(screen.getByRole('button', { name: /search/i }))
    expect(await screen.findByText(/hold the button/i)).toBeInTheDocument()
    expect(screen.getByText(/87% match/i)).toBeInTheDocument()
  })

  it('clears stale search results once the document set changes', async () => {
    vi.mocked(searchKb).mockResolvedValue({
      hits: [{ document_id: 'd1', filename: 'reset-guide.md', content: 'Hold the button', score: 0.87 }],
    })
    vi.mocked(deleteKbDocument).mockResolvedValue({ deleted: true })
    render(<KnowledgeBasePanel />)
    await screen.findByText('reset-guide.md')
    await userEvent.type(screen.getByLabelText(/test search/i), 'reset')
    await userEvent.click(screen.getByRole('button', { name: /search/i }))
    expect(await screen.findByText(/hold the button/i)).toBeInTheDocument()

    vi.mocked(fetchKbDocuments).mockResolvedValue([])
    await userEvent.click(screen.getByRole('button', { name: /delete/i }))

    expect(await screen.findByText(/no documents uploaded yet/i)).toBeInTheDocument()
    expect(screen.queryByText(/hold the button/i)).not.toBeInTheDocument()
  })

  it('surfaces an upload error', async () => {
    vi.mocked(uploadKbDocument).mockRejectedValue(new Error('too large'))
    render(<KnowledgeBasePanel />)
    await screen.findByText('reset-guide.md')
    const file = new File(['x'], 'big.txt', { type: 'text/plain' })
    await userEvent.upload(screen.getByLabelText(/upload document/i), file)
    expect(await screen.findByRole('alert')).toBeInTheDocument()
  })
})
