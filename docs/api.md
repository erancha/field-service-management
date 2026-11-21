# API endpoints

This document details every route behind the entry points that
[Architecture](architecture.md#the-entry-points) summarizes: who may call it, what it takes and
answers, and its limits. The page reaches the role processes through the `nginx` edge; the
`worker` serves no HTTP, and the work it does is in
[Workers' responsibilities and flows](workers.md).

## Role HTTP API (`technician`, `customer` and `backoffice` services)

FastAPI in `backend/src/fsm/platform/` (`app.py` and the routers under `api/`). Every role process
declares the same routes; what a caller may reach is decided by the role of their session, and a
session belongs to the role app it was signed in at ([Sign-in](sign-in.md#who-may-sign-in)).
"Signed in" below means any session; a named role means a session of that role whose approval is
granted, else 403. Every route under `/api` needs a session, and a route that needs one answers
401 without it.

### Sign-in and profile

- `GET /auth/google/login` — starts the Google sign-in and redirects to Google; 503 while the
  Google client is not configured ([Sign-in](sign-in.md#how-it-works)).
- `GET /auth/google/callback` — completes it: checks the `state`, redeems the code, assigns this
  process's role and redirects to `/`; 403 at the back office for an account outside
  `ADMIN_EMAILS`. A technician's first sign-in publishes the access request to the back office
  ([Live events](live-events.md#flows)).
- `GET /auth/me` — the signed-in person: id, email, role, its approval, name, the profile fields
  and when they accepted the assistant's disclaimer, read from the database on every call.
- `PATCH /auth/me` — updates the profile fields the body names (`display_name`, `address`,
  `phone`); 422 for an invalid phone number.
- `POST /auth/me/assist-disclaimer` — records that the person accepted the assistant's
  disclaimer; a repeat keeps the first time.
- `POST /auth/logout` — clears the session.

### Calendar connect

The technician routes of [Google Calendar connect](calendar-setup.md#how-connecting-works).

- `GET /calendar/connect/login` — technician: starts the calendar consent and redirects to Google;
  503 while the calendar is not configured.
- `GET /calendar/connect/callback` — technician: completes it, creates the app's calendar and
  stores the encrypted refresh token, then redirects to `/`, or to `/?calendar_connect=denied` on a
  refused or cancelled consent.
- `POST /calendar/disconnect` — technician: marks the connection disconnected, which drops the
  technician from pooled availability; 404 without a connection.
- `GET /calendar/status` — signed in: whether the caller's calendar is connected, and its id.

### Service calls and appointments

- `POST /api/service-calls` — customer: opens a service call with its `description` (201).
- `GET /api/service-calls/{service_call_id}/photos/{photo_id}` — one photo of a call, `original`
  or a preview `variant`, for the call's customer, a technician with an appointment on it, or an
  administrator; 503 while the photo store is not configured.
- `POST /api/appointments` — customer: books an approved technician for one of the customer's own
  open calls, from `start` to `end`; 409 when the slot overlaps another appointment, 422 while the
  contact details a booking needs are missing, 429 past the cancellation churn limit.
- `POST /api/appointments/{appointment_id}/reschedule` — the appointment's customer or technician:
  moves it to a new `start` and `end`; 409 on an overlap or a transition its status forbids.
- `POST /api/appointments/{appointment_id}/cancel` — the appointment's customer or technician.
- `POST /api/appointments/{appointment_id}/details` — the appointment's customer or technician:
  attaches or replaces its free-text `details`.
- `GET /api/appointments/upcoming` — signed in: the soonest `limit` upcoming appointments, a
  technician's or a customer's own, every one for an administrator, each with the problem, the
  triage summary, both names, the address and the call's photos.

Each change to an appointment publishes a live event to both parties and is carried to Google
Calendar through the outbox ([Workers](workers.md#calendarprojectiondispatcher)).

### Availability

- `GET /api/availability` — signed in: one technician's free slots between `date_from` and
  `date_to`, `slot_minutes` long (60 by default), after working hours, days off, public holidays
  and Google free/busy.
- `GET /api/availability/pool` — signed in: the same across every approved technician with a
  connected calendar, each slot naming its technician, earliest first, the first `limit` when
  given.

### Technician schedule

A technician acts on their own schedule only; another technician's id answers 403.

- `GET /api/technicians/{technician_id}/working-hours` — technician: the weekly windows, a default
  when none is set.
- `PUT /api/technicians/{technician_id}/working-hours` — technician: replaces the weekly
  `windows`, each a `weekday` with a `start` and an `end`.
- `GET /api/technicians/{technician_id}/days-off` — technician: the days off between `date_from`
  and `date_to`.
- `POST /api/technicians/{technician_id}/days-off` — technician: marks a `date` off (201); a repeat
  is harmless.
- `DELETE /api/technicians/{technician_id}/days-off/{off_date}` — technician: removes a day off
  (204).

### Triage chat

The customer's assistant ([Features](features.md#the-customers-triage-assistant)). A customer
reaches only their own conversations.

- `GET /api/assist/status` — signed in: whether the chat is configured, which decides between the
  chat and the plain description form.
- `POST /api/assist/conversations` — customer: the active conversation, started when there is
  none, with its photos not yet sent.
- `GET /api/assist/conversations` — customer: the ended conversations, newest first, each as a
  one-line summary.
- `GET /api/assist/conversations/{conversation_id}` — customer: one conversation's transcript.
- `POST /api/assist/conversations/{conversation_id}/messages` — customer: one turn of `text`,
  attached `photo_ids` or both; the reply streams as server-sent events, `token` fragments then a
  `done` event with the conversation's status, the yes/no question's offsets, the service call it
  opened and the documents it rests on. 404 for an unknown conversation or photo, 409 for an ended
  conversation.
- `POST /api/assist/conversations/{conversation_id}/end` — customer: ends the conversation with no
  service call and discards the photos not yet sent.
- `POST /api/assist/conversations/{conversation_id}/photos` — customer: attaches a photo to the
  next turn (201), up to five per conversation; 413 above 5 MB.
- `GET /api/assist/conversations/{conversation_id}/photos/{photo_id}` — customer: one photo of the
  conversation, `original` or a preview `variant`.
- `DELETE /api/assist/conversations/{conversation_id}/photos/{photo_id}` — customer: detaches a
  photo not yet sent (204).

### Knowledge base

The documents the assistant answers from. Every route but the status and the content answers 503
while the embeddings model is not configured.

- `GET /api/kb/status` — administrator: whether the knowledge base is configured, its embeddings
  model and whether the stored documents need a reindex.
- `GET /api/kb/documents` — administrator: the uploaded documents.
- `POST /api/kb/documents` — administrator: uploads a document, which is chunked, embedded and
  indexed (201), its progress published on the administrator's event stream; 413 above 20 MB.
- `DELETE /api/kb/documents/{document_id}` — administrator: removes a document and its indexed
  chunks.
- `GET /api/kb/documents/{document_id}/content` — signed in: the document's original bytes,
  served inline, so the customer can open a document the assistant names.
- `POST /api/kb/search` — administrator: the chunks nearest a `query`, with their scores.
- `POST /api/kb/reindex` — administrator: re-chunks and re-embeds every stored document.

### Back office

- `GET /api/back-office/technician-requests` — administrator: the technicians awaiting approval.
- `POST /api/back-office/technician-requests/{user_id}/approve` — administrator: approves one and
  tells them live ([Live events](live-events.md#technician-approval--dashboard-live)).
- `POST /api/back-office/technician-requests/{user_id}/reject` — administrator: rejects one, the
  same way.

### Event stream

- `GET /api/events` — signed in: the caller's server-sent event stream, over their own channel
  and, for an approved administrator, the back office's
  ([Live events across replicas](live-events.md)).

### Probes and the page

- `GET /health` — answers while the process runs.
- `GET /ready` — also needs the database to answer; 503 when it does not.
- `GET /` — a minimal landing page naming the role, when the process serves no built page; with
  `FSM_FRONTEND_DIST` set, the process serves the built page at `/` instead.

FastAPI's own API documentation is at `/docs` and `/redoc`, with the schema at `/openapi.json`.

## The edge (`nginx` service)

The edge has one server block per role, on ports 8001 to 8003 (`nginx/default.conf`). Each
answers `/` and every other path outside the API with the built page, so the page's own routes
load on a deep link, and passes `/api`, `/auth`, `/calendar`, `/docs`, `/redoc`, `/openapi.json`,
`/health` and `/ready` to its role's processes.
