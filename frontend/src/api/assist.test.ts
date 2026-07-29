import { describe, expect, it, vi, afterEach } from 'vitest'
import { listPastConversations, streamAssistReply } from './assist.ts'

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

    const result = await streamAssistReply('c1', 'It will not heat.', (t) => tokens.push(t))

    expect(tokens.join('')).toBe('Is it lit?')
    expect(result.status).toBe('ACTIVE')
    expect(result.service_call).toBeNull()
  })

  it('surfaces the created service call on escalation', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(sseResponse([
      'event: token\ndata: {"text":"Booking a visit."}\n\n',
      'event: done\ndata: {"status":"ESCALATED","service_call":{"id":"sc-1","description":"Equipment: Oven"}}\n\n',
    ])))

    const result = await streamAssistReply('c1', 'Still cold.', () => {})

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

    await streamAssistReply('c1', 'hi', (t) => tokens.push(t))

    expect(tokens.join('')).toBe('Split')
  })

  it('throws with the server detail on an error response', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ detail: 'Conversation already ended' }), { status: 409 }),
    ))

    await expect(streamAssistReply('c1', 'hi', () => {}))
      .rejects.toThrow('Conversation already ended')
  })

  it('throws when the stream ends without a done frame', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(sseResponse([
      'event: token\ndata: {"text":"cut off"}\n\n',
    ])))

    await expect(streamAssistReply('c1', 'hi', () => {})).rejects.toThrow()
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
