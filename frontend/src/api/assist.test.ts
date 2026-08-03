import { describe, expect, it, vi, afterEach } from 'vitest'
import * as client from './client.ts'

vi.mock('./client.ts', async (importOriginal) => {
  const actual = await importOriginal<typeof client>()
  return { ...actual, apiUpload: vi.fn() }
})

const { listPastConversations, streamAssistReply, uploadTriagePhoto, deleteTriagePhoto, triagePhotoUrl } =
  await import('./assist.ts')

function sseResponse(frames: string[]): Response {
  const stream = new ReadableStream<Uint8Array>({
    start(controller) {
      const encoder = new TextEncoder()
      for (const frame of frames) controller.enqueue(encoder.encode(frame))
      controller.close()
    },
  })
  return new Response(stream, {
    status: 200,
    headers: { 'Content-Type': 'text/event-stream' },
  })
}

afterEach(() => { vi.unstubAllGlobals() })

describe('streamAssistReply', () => {
  it('delivers tokens in order and resolves with the ending', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(sseResponse([
      'event: token\ndata: {"text":"Is "}\n\n',
      'event: token\ndata: {"text":"it lit?"}\n\n',
      'event: done\ndata: {"status":"ACTIVE","service_call":null}\n\n',
    ])))
    const tokens: string[] = []

    const result = await streamAssistReply('c1', 'It will not heat.', [], (t) => tokens.push(t))

    expect(tokens.join('')).toBe('Is it lit?')
    expect(result.status).toBe('ACTIVE')
    expect(result.service_call).toBeNull()
  })

  it('surfaces the created service call on escalation', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(sseResponse([
      'event: token\ndata: {"text":"Booking a visit."}\n\n',
      'event: done\ndata: {"status":"ESCALATED","service_call":{"id":"sc-1","description":"Equipment: Oven"}}\n\n',
    ])))

    const result = await streamAssistReply('c1', 'Still cold.', [], () => {})

    expect(result.status).toBe('ESCALATED')
    expect(result.service_call?.id).toBe('sc-1')
  })

  it('reassembles a frame split across chunks', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(sseResponse([
      'event: token\ndata: {"te',
      'xt":"Split"}\n\n',
      'event: done\ndata: {"status":"ACTIVE","service_call":null}\n\n',
    ])))
    const tokens: string[] = []

    await streamAssistReply('c1', 'hi', [], (t) => tokens.push(t))

    expect(tokens.join('')).toBe('Split')
  })

  it('throws with the server detail on an error response', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ detail: 'Conversation already ended' }), { status: 409 }),
    ))

    await expect(streamAssistReply('c1', 'hi', [], () => {}))
      .rejects.toThrow('Conversation already ended')
  })

  it('throws when the stream ends without a done frame', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(sseResponse([
      'event: token\ndata: {"text":"cut off"}\n\n',
    ])))

    await expect(streamAssistReply('c1', 'hi', [], () => {})).rejects.toThrow()
  })

  it('sends the attached photo ids with the turn', async () => {
    const fetchMock = vi.fn().mockResolvedValue(sseResponse([
      'event: done\ndata: {"status":"ACTIVE","service_call":null}\n\n',
    ]))
    vi.stubGlobal('fetch', fetchMock)

    await streamAssistReply('c1', 'Here', ['p1', 'p2'], () => {})

    expect(JSON.parse(fetchMock.mock.calls[0][1].body)).toEqual({
      text: 'Here',
      photo_ids: ['p1', 'p2'],
    })
  })
})

describe('uploadTriagePhoto', () => {
  it('posts the file as multipart form data to the conversation photos endpoint', async () => {
    const photo = { id: 'p1', filename: 'plate.jpg', size_bytes: 3 }
    vi.mocked(client.apiUpload).mockResolvedValue(photo)
    const file = new File(['x'], 'plate.jpg', { type: 'image/jpeg' })

    const result = await uploadTriagePhoto('c1', file)

    expect(result).toEqual(photo)
    const [path, form] = vi.mocked(client.apiUpload).mock.calls[0]
    expect(path).toBe('/api/assist/conversations/c1/photos')
    expect((form as FormData).get('file')).toBe(file)
  })
})

describe('deleteTriagePhoto', () => {
  it('sends a DELETE to the conversation photo path and tolerates the 204 response', async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response(null, { status: 204 }))
    vi.stubGlobal('fetch', fetchMock)

    await deleteTriagePhoto('c1', 'p1')

    expect(fetchMock).toHaveBeenCalledWith(
      '/api/assist/conversations/c1/photos/p1',
      expect.objectContaining({ method: 'DELETE' }),
    )
  })
})

describe('triagePhotoUrl', () => {
  it('builds the photo path for a conversation, naming the variant it wants', () => {
    expect(triagePhotoUrl('c1', 'p1', 'preview')).toBe(
      '/api/assist/conversations/c1/photos/p1?variant=preview',
    )
    expect(triagePhotoUrl('c1', 'p1', 'original')).toBe(
      '/api/assist/conversations/c1/photos/p1?variant=original',
    )
  })
})

describe('listPastConversations', () => {
  it('unwraps the conversations of the history payload', async () => {
    const summary = {
      id: 'c1',
      status: 'SOLVED',
      updated_at: '2026-07-24T09:00:00+00:00',
      opening_line: 'No hot water.',
    }
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ conversations: [summary] }), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      }),
    ))

    expect(await listPastConversations()).toEqual([summary])
  })
})
