# Redis event bus + SSE sample

A narrowed stack for one mechanism of the main application: an event published in one backend
process reaching an SSE stream held open by another, through the Redis pub/sub broker. Everything
generic is imported from the application, not copied — the backends use `fsm.core.events`
(`build_event_bus`, `RedisEventBus`) from the `fsm-backend:local` image, and the page uses the
shared-EventSource hook `frontend/src/hooks/useEventStream.ts`.

## Flow

```mermaid
sequenceDiagram
    participant Browser as Browser (useEventStream)
    participant Proxy as frontend (Vite proxy)
    participant B1 as backend-1 (SSE route)
    participant Redis as redis
    participant B2 as backend-2 (publish route)

    Browser->>Proxy: GET /api/events (one EventSource per page)
    Proxy->>B1: GET /api/events
    Note over B1: generates a random stream id per connection<br/>(e.g. "d9c8d8f3" — the example id used below)<br/>logs: SSE stream 'd9c8d8f3' opened on channel 'sample'
    B1->>Redis: SUBSCRIBE "sample"
    Note over B1,Redis: bus.subscribe({"sample"}, stream_id="d9c8d8f3") yields an<br/>asyncio.Queue — the piece that joins the Redis channel<br/>to this one SSE connection

    Browser->>Proxy: POST /api/publish {"message": "hello"}
    Proxy->>B2: POST /api/publish
    B2->>Redis: PUBLISH "sample" {"type": "sample.message", "message": "hello"}
    Note over B2: logs: Published 'sample.message' to channel 'sample' (1 subscriber(s))

    Redis-->>B1: message on channel "sample"
    Note over B1: the subscription's pump decodes the JSON and enqueues it<br/>logs: Received 'sample.message' from channel 'sample'<br/>to the queue of stream 'd9c8d8f3'
    Note over B1: the SSE loop wakes on the queue<br/>logs: Delivering 'sample.message' on stream 'd9c8d8f3'
    B1-->>Proxy: event: sample.message<br/>data: {"type": "sample.message", "message": "hello"}
    Proxy-->>Browser: same SSE frame
    Note over Browser: the hook dispatches the payload to the<br/>'sample.message' handler and the list re-renders
```

`backend-1` and `backend-2` run the identical sample app (`backend/app.py`), which serves both a
publish route and an SSE route. The Vite proxy is what assigns roles: it pins the page's SSE
stream to backend-1 and the publish POST to backend-2, so every posted message must cross
processes through Redis before it reappears on the page. The sample uses one fixed channel
(`sample`) where the application derives per-user and admins channels from the session — channel
naming is the application's job, not the transport's.

## Run

```bash
docker compose up --build
```

Then open <http://localhost:8010>, type a message, and post it. It should appear in the list below
the form immediately — delivered via the SSE stream, not the POST response.

The logs show the full path, tied together by the delivery-trace ids:

```bash
docker compose logs backend-1 backend-2
# backend-2  ... Published 'sample.message' to channel 'sample' (1 subscriber(s))
# backend-1  ... Received 'sample.message' from channel 'sample' to the queue of stream '<id>'
# backend-1  ... Delivering 'sample.message' on stream '<id>'
```

## Test

```bash
./test.sh
```

The script does what the page does, against the real stack. It starts the compose stack unless one
is already running, opens the SSE stream, posts a message, and passes only if the message comes
back on the stream and the logs show the publish on backend-2 and the delivery on backend-1. On
success it prints those log lines in timestamp order. If the script started the stack it also
shuts it down at the end; a stack you started yourself is left running.

A second, faster check needs no Docker at all. It runs the sample app in-process with the
in-memory bus standing in for Redis, posts to the publish route, and asserts the event reaches a
subscriber of the `sample` channel. It borrows the main backend's virtualenv, since the sample
installs nothing of its own:

```bash
cd backend && ../../../backend/.venv/bin/pytest test_app.py
```
