type Listener = (event: MessageEvent) => void

/** In-test stand-in for the browser EventSource, letting tests drive SSE events and reconnects. */
export class FakeEventSource {
  static instances: FakeEventSource[] = []

  url: string
  onopen: ((ev: Event) => void) | null = null
  closed = false
  private listeners: Record<string, Listener[]> = {}

  constructor(url: string) {
    this.url = url
    FakeEventSource.instances.push(this)
  }

  addEventListener(type: string, cb: Listener): void {
    ;(this.listeners[type] ??= []).push(cb)
  }

  removeEventListener(type: string, cb: Listener): void {
    this.listeners[type] = (this.listeners[type] ?? []).filter((l) => l !== cb)
  }

  close(): void {
    this.closed = true
  }

  emit(type: string, data: unknown): void {
    for (const cb of this.listeners[type] ?? []) {
      cb({ data: JSON.stringify(data) } as MessageEvent)
    }
  }

  open(): void {
    this.onopen?.(new Event('open'))
  }

  static reset(): void {
    FakeEventSource.instances = []
  }

  static last(): FakeEventSource {
    return FakeEventSource.instances[FakeEventSource.instances.length - 1]
  }
}
