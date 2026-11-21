# Workers' responsibilities and flows

This document details the work no request waits on, behind the entry points that
[Architecture](architecture.md#the-entry-points) summarizes: the `worker` service's two calendar
loops, the one-shot schema migration, and the two jobs run by hand. The routes whose writes the
loops carry to Google are in [API endpoints](api.md).

**Contents:** [The worker service](#the-worker-service) ·
[`CalendarProjectionDispatcher`](#calendarprojectiondispatcher) · [`sync_runner`](#sync_runner) ·
[`migrate`](#migrate) · [`holiday_refresh`](#holiday_refresh) ·
[`backfill_customer_attendees`](#backfill_customer_attendees)

## The worker service

The background calendar workers run in a `worker` deployment of their own
(`fsm/platform/roles.py`, `python -m fsm.platform.worker`), which serves no HTTP. Keeping them out
of the role processes is what lets every role scale — a second technician or back-office replica
adds no calendar work. Within the worker deployment, the outbound dispatcher is safe to run
concurrently (it claims outbox rows with `FOR UPDATE SKIP LOCKED`), while the inbound poller must
be single: it takes a lease, a Postgres advisory lock, before polling, and a process that loses it
stands by and retries, so a second worker replica is a warm standby that takes over when the
holder dies. Each loop runs in a daemon thread named after it (`fsm-dispatcher`, `fsm-sync`), which
is how the logs identify it.

The two loops keep Google Calendar aligned with the database. Both directions treat PostgreSQL as
the merge authority: Google is a projection, so any conflict resolves in the database's favour.

## `CalendarProjectionDispatcher`

**Outbound projection (database → Google).** A confirmed appointment change (create, reschedule,
cancel) enqueues a `calendar_outbox` row in the same transaction as the appointment write, so a
calendar outage can never lose a booking. `CalendarProjectionDispatcher` — run by
`dispatcher_runner` in the worker deployment, every `FSM_DISPATCH_INTERVAL_SECONDS` (default 5s)
— claims one `PENDING` entry at a time with `SELECT … FOR UPDATE SKIP LOCKED`, performs the
Google operation, writes back the `external_event_id`, and commits per entry. Each event carries a
deterministic iCalUID, so a retry after a crash re-finds the existing event (Google answers a
duplicate insert with HTTP 409) rather than creating a second one. Transient failures keep the
entry `PENDING` until `MAX_ATTEMPTS`, then dead-letter it to `FAILED`.

## `sync_runner`

**Inbound reconciliation (Google → database).** `sync_runner`, in the worker deployment every
`FSM_SYNC_INTERVAL_SECONDS` (default 30s), polls each technician's calendar using the stored
`sync_token` for incremental changes. `calendar_bridge/inbound_sync` maps each raw event to an
`InboundEventChange` and discards events whose iCalUID is not FSM-owned. `reconciliation_service`
then applies the change under last-write-wins arbitration — the Google event's last-modified time
against the appointment's `updated_at`: a stale edit is dropped, a customer decline or technician
cancel updates the row, and an edit that conflicts with the booking policy loses to the database
and enqueues a re-projection `UPDATE` back onto the outbox. Each committed change publishes an
event so the affected participants' open views refresh live.

## `migrate`

The Compose service `migrate` runs `alembic upgrade head` once per start, after Postgres reports
healthy, and each role starts only after it has completed and Postgres, Redis and the object store
report healthy; nginx starts after the roles do. The migrations are under
`backend/alembic/versions` ([Data model](data-model.md)).

## `holiday_refresh`

`python -m fsm.platform.holiday_refresh` is a one-shot job that fetches the public holidays of
`HOLIDAY_CALENDAR_ID` with `GOOGLE_API_KEY`, from today to `HOLIDAY_REFRESH_YEARS_AHEAD` years
ahead, and upserts them into the `holiday` table that availability excludes. It does nothing when
either setting is unset, and a failed fetch logs a warning and keeps the stored holidays. Nothing
in the stack schedules it.

## `backfill_customer_attendees`

`python -m fsm.platform.backfill_customer_attendees` is a one-time job that enqueues a
re-projection `UPDATE` on the outbox for every active, future, already-projected appointment, so
the dispatcher adds the customer as a guest on the event. A repeat run projects the same state but
emails every active customer again.
