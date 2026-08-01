# Features & roadmap

## What's built

Everything below is running today. Everything not below is in the [Roadmap](#roadmap).

### Sign-in and roles

Google OIDC is the only sign-in path, so its environment variables are required configuration and
every booking or scheduling action needs a signed-in session. There are three roles — customer,
technician, and admin — and a role comes from the per-role edge that completed the sign-in, never
from client input. An admin approves a technician before they can be booked.

### Booking and scheduling

- Customers book themselves, against a technician's real availability.
- **No double-booking is enforced by the database**, not by application checks: a GiST exclusion
  constraint rejects any overlapping appointment for the same technician.
- Availability subtracts per-technician working hours and time off, central holiday exclusions, and
  the technician's Google free/busy.
- Either side can reschedule or cancel; every booking action lands in an append-only audit.

### Google Calendar, both directions

- **Outbound:** every appointment is projected to the technician's calendar through a transactional
  outbox, so a calendar failure can never lose a booking that the database accepted.
- **Inbound:** a poll reconciles edits the technician made on Google's side.
- The customer is added as a **real guest**, so Google itself delivers the invite, updates, and
  cancellation.
- A guest declining or deleting the event cancels the appointment. A guest moving the event is
  validated against the technician's availability, and reverted with a notification when the new
  time is not bookable.
- The technician's event carries the triage summary laid out as HTML — the fault and symptoms and
  what to do first, then the equipment, suspected cause, and what has been ruled out.

### Notifications

An in-app feed for both parties, plus an email to the technician. Email is configured by environment
variables and degrades gracefully when unset — the feed row is still written.

### The customer's triage assistant

**An assistant today, an agent on the way.** The model holds the conversation and marks when triage
is over; the code around it takes the one action that follows — opening the service call. The model
calls no tools; letting it act across the call lifecycle is what would make it an agent.

Replies are grounded in the back-office knowledge base by retrieval-augmented generation: every
customer turn is embedded, the nearest chunks come back from pgvector and enter the system prompt as
reference material the model follows and cites by document name, falling back to its own knowledge
when no uploaded document covers the topic. Retrieval repeats per turn, because the topic can move
mid-chat.

The chat appears when `ASSIST_MODEL` and its provider's API key are set; with them unset the
customer sees the plain description form instead, and switching between an Anthropic and an OpenAI
model is a change to `ASSIST_MODEL` and its key, with no code change. The assistant suggests only
steps that are safe for a customer to try — never gas, mains wiring, refrigerant, or working at
height.

Before a customer first reaches their dashboard, a disclaimer states what the assistant is: it
answers from the uploaded knowledge base and names the document, falls back on the model's training
data where no document covers the question, and is to be checked rather than followed. Nothing it
suggests is a reason to work on gas, mains wiring, refrigerant, or at height. Continuing needs a
ticked confirmation, recorded on the account as a timestamp
(`app_user.assist_disclaimer_accepted_at`) rather than in browser storage, so a customer is asked
once rather than once per device — and is asked even where `ASSIST_MODEL` is unset.

The assistant is told to put its question as one a yes or no answers whenever a yes or no would
tell it what it needs — to name the thing it suspects and let the customer confirm or deny it
("do you see anything built up on the rail?") rather than send them off to observe and report
("look at the rail and tell me what you see"), since a denial rules the suspicion out just as well.
Questions stay open only where no yes or no could carry the answer: a model number, an error code,
a reading. A message that prescribes a step closes the same way, asking after that step's result as
a yes/no that names it ("did cleaning the rail stop the juddering?"), so a suggestion never leaves
the customer with an instruction and nothing to answer.

When the assistant's one question is a plain yes/no ("Is the breaker on?"), the chat shows tappable
Yes and No quick-reply buttons. Beside them sits a Send tick-box, on by default: a tap then answers
the question in one turn. Clearing it redirects the tap into the composer instead, unsent and ready
to be qualified — "Yes, on the control box" — for a question where yes or no is only the opening of
the answer. Either way a tap folds in anything already typed rather than stranding it, and
answering retires the buttons so a second tap cannot stack a second answer.

The assistant marks such a question by wrapping it in delimiters, which the server strips before
storing the reply and reports as offsets into the visible text on the turn's final SSE frame. The
browser therefore learns both facts from data: that buttons belong on this turn, and where the
question they answer sits, so it bolds that question without inspecting the reply itself. History
read back after a conversation ends carries no offsets and so shows neither buttons nor emphasis.

Marking the question in place is what keeps that signal dependable: the delimiters are written as
part of the question, so a question the model has finished writing cannot be missing them. Because
they sit mid-reply, the stream removes each one where it stands and carries on, which is what lets
the question reach the customer as it is written rather than in one lump when the turn ends.

A conversation ends one of three ways:

- **Solved** — the customer confirms the problem is fixed.
- **Escalated** — the assistant first asks, as a yes/no question, whether to book a technician
  visit; only a Yes opens the service call carrying the summary, after which the customer books a
  technician through the same flow as before. A No stays in the conversation for one more try or a
  late correction — though a declined safety escalation reopens nothing unsafe: the assistant
  repeats that a technician is the safe way forward.
- **Closed** — it was never an equipment fault, or the customer asked to stop. Booking nothing is
  the point, so asking to leave never books a visit. Both the assistant and an End chat button can
  close one.

The summary is **stored as structure, not prose**: the service call keeps the fields as JSON, and
one layout definition drives the calendar event's HTML, the appointment card, and the notification
email, so no surface reads a rendering back apart.

Around the edges: a conversation that runs long escalates on its own, without the booking question,
because each turn re-sends the whole exchange and a customer still stuck that far in needs a visit; one left quiet for 24 hours is
retired; a customer has at most one active conversation, enforced by a partial unique index; replies
stream to the browser and survive a page reload; ended conversations stay readable, newest first;
and a conversation nobody typed into never appears. Opening a service call never depends on the
assistant — a turn the model cannot answer offers the plain description form as a way through.

### Photos in the chat

A customer can attach up to five photos per conversation (JPEG, PNG, or WebP, 5 MB each) — a rating
plate, a display error code, the state of a part.

- The assistant never sees the original: it gets a downscaled, EXIF-stripped copy (long edge
  1280px), reads what it shows, and quotes back a model number or error code it can make out.
- It stops suggesting steps and escalates the moment a photo shows a risk signal — scorch marks,
  exposed wiring, water near electrics, gas fittings.
- Originals live in the bundled MinIO service; Postgres keeps only metadata rows, never photo bytes.
- Every non-escalated ending reclaims the conversation's photos. For a 24-hour retirement that
  reclamation is lazy, done when the customer next opens the chat, not by a background job.
- An escalated ending carries the sent photos onto the service call as attachments, shown as preview
  thumbnails on the technician's appointment card. The original is downloadable by the call's
  customer, a technician with an appointment on the call, or an admin — no one else.
- Calendar events carry the call's text summary, never a photo.
- Both the images and the problem text are sent to the configured chat-model provider, the same
  third-party posture as the rest of the chat.

### Knowledge base

The back office uploads the documents the assistant answers from. An upload is chunked, embedded,
and indexed into pgvector; a byte-identical re-upload is rejected rather than indexed twice; and the
panel stays usable as the library grows.

### Deployment

`./scripts/start.sh` runs the whole stack locally in Docker or as host processes
([Getting started](../README.md#getting-started)). `scripts/deploy-to-ec2/` serves the three role
apps publicly from a single ARM EC2 box over HTTPS, with certificates renewed in the background.

## Roadmap

The [vision document](https://docs.google.com/document/d/1bX7L_CL6hBIfpJVCkpRFYk6hIZ7OxD7dSugnPWCKLsY/edit)
describes the full product. What is not built yet is tracked as issues rather than described here, so
this page stays a record of what runs and the tracker stays the record of what is next. Everything
below carries the [`Long term`](https://github.com/erancha/field-service-management/labels/Long%20term)
label; smaller follow-ups live in the tracker alongside them.

| Track | Open work |
|---|---|
| Back office | [#81](https://github.com/erancha/field-service-management/issues/81) customers, sites, and contacts · [#82](https://github.com/erancha/field-service-management/issues/82) asset catalog and fault history · [#83](https://github.com/erancha/field-service-management/issues/83) call lifecycle past SCHEDULED, with a dispatch board · [#90](https://github.com/erancha/field-service-management/issues/90) search · [#91](https://github.com/erancha/field-service-management/issues/91) parts and inventory |
| Technician field app | [#84](https://github.com/erancha/field-service-management/issues/84) route and navigation · [#85](https://github.com/erancha/field-service-management/issues/85) check-in/out and time logging · [#86](https://github.com/erancha/field-service-management/issues/86) service report, signature, signed PDF · [#87](https://github.com/erancha/field-service-management/issues/87) offline use |
| Customer app | [#89](https://github.com/erancha/field-service-management/issues/89) live status, on-the-way alert, report download |
| Platform | [#88](https://github.com/erancha/field-service-management/issues/88) push and SMS channels · [#92](https://github.com/erancha/field-service-management/issues/92) audit trail across the lifecycle |
