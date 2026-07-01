# Database schema

PostgreSQL is the system's source of truth; Google Calendar is a downstream projection, never a
store of record. The schema is owned by the bounded contexts<sup>(1)</sup> — `identity`, `scheduling`,
`calendar`, and `notifications` — and lives in each context's `adapters/orm.py`, with Alembic<sup>(2)</sup>
migrations under `backend/migrations/versions`.

There is one identity table, `app_user`: technician, customer, and administrator are roles on that
row, not separate entities. Cross-context references (a technician, a customer) are plain `UUID`<sup>(3)</sup>
columns pointing at `app_user.id`; they are application-level relationships, not database foreign
keys, so each context can be migrated and reasoned about independently. The relationships drawn below
are those logical links.

```mermaid
erDiagram
    APP_USER ||--o{ SERVICE_CALL : "places (customer_id)"
    APP_USER ||--o{ APPOINTMENT : "assigned (technician_id)"
    APP_USER ||--o{ NOTIFICATION : "receives (user_id)"
    APP_USER ||--o| CALENDAR_CONNECTION : "connects (technician_id)"
    APP_USER ||--o{ TIME_OFF : "marks (technician_id)"
    APP_USER ||--o{ WORKING_HOURS : "sets (technician_id)"
    APP_USER ||--o| TECHNICIAN_TIMEZONE : "sets (technician_id)"
    SERVICE_CALL ||--o{ APPOINTMENT : "scheduled as (service_call_id)"
    APPOINTMENT ||--o{ APPOINTMENT_AUDIT : "logs (appointment_id)"
    APPOINTMENT ||--o{ CALENDAR_OUTBOX : "projects via (appointment_id)"

    APP_USER {
        uuid id PK
        string google_sub UK
        string email
        string name
        string role "CUSTOMER | TECHNICIAN | ADMIN"
        string role_status "PENDING | APPROVED | REJECTED"
        timestamptz role_decided_at "null until decided"
        uuid role_decided_by "deciding admin"
    }

    SERVICE_CALL {
        uuid id PK
        uuid customer_id
        string description
        string status "OPEN | SCHEDULED | CANCELLED"
        timestamptz created_at
    }

    APPOINTMENT {
        uuid id PK
        uuid service_call_id
        uuid technician_id
        uuid customer_id
        timestamptz start_at
        timestamptz end_at
        string status
        string details "nullable"
        string external_event_id "Google event id, nullable"
        timestamptz created_at
        timestamptz updated_at
    }

    APPOINTMENT_AUDIT {
        uuid id PK
        uuid appointment_id "indexed"
        string action
        timestamptz occurred_at
    }

    CALENDAR_OUTBOX {
        uuid id PK
        string operation "CREATE | UPDATE | DELETE"
        uuid appointment_id
        string external_event_id "nullable"
        string status "PENDING | PROCESSED | FAILED"
        int attempts
        timestamptz created_at
        timestamptz processed_at "nullable"
        text last_error "nullable"
    }

    CALENDAR_CONNECTION {
        uuid technician_id PK
        string fsm_calendar_id
        text encrypted_refresh_token
        string status
        text sync_token "nullable"
    }

    NOTIFICATION {
        uuid id PK
        uuid user_id "indexed"
        text kind
        text subject
        text body
        timestamptz created_at
        boolean read
    }

    TIME_OFF {
        uuid technician_id PK
        date off_date PK
    }

    WORKING_HOURS {
        uuid technician_id PK
        smallint weekday PK "0=Mon … 6=Sun"
        time start_time
        time end_time
    }

    TECHNICIAN_TIMEZONE {
        uuid technician_id PK
        text timezone "IANA name"
    }

    HOLIDAY {
        date holiday_date PK
        text name
    }
```

`HOLIDAY` stands alone — a per-date cache of public holidays excluded from availability, with no
link to any other entity.

## Integrity guarantees worth knowing

- **No double-booking.** A GiST exclusion constraint<sup>(4)</sup> on `appointment` rejects any two non-cancelled
  appointments for the same technician whose `[start_at, end_at)` windows overlap — the
  no-double-booking promise is enforced in the database, not just in application code.
- **Calendar projection is transactional.** Confirmed appointment changes enqueue a `calendar_outbox`<sup>(5)</sup>
  row in the same transaction; a background dispatcher drains it onto Google with bounded retries
  (`PENDING → PROCESSED`, or `→ FAILED` after repeated failures), so a calendar outage never loses a
  booking.
- **Appointment history is append-only.** Every lifecycle transition writes an `appointment_audit`
  row in the appointment's own transaction, keeping the log consistent with entity state.
- **One connection / window per technician.** `calendar_connection` and `technician_timezone` key on
  `technician_id` alone; `working_hours` and `time_off` use composite keys so a technician has at
  most one window per weekday and one row per day off.

## Glossary

In the diagram, `PK` marks a primary key, `UK` a unique key, and an `IANA name` is a timezone
identifier from the IANA database (for example `Europe/Berlin`).

| Ref | Term | Meaning |
| --- | --- | --- |
| (1) | bounded context | A self-contained slice of the domain (`identity`, `scheduling`, `calendar`, `notifications`) that owns its own tables and is migrated and reasoned about independently of the others. |
| (2) | Alembic | The SQLAlchemy migration tool; each context's schema changes are versioned as migration scripts under `backend/migrations/versions`. |
| (3) | UUID — Universally Unique Identifier | A 128-bit identifier used as every table's key, so rows can be referenced across contexts without a shared database sequence. |
| (4) | GiST exclusion constraint | A PostgreSQL constraint backed by a Generalized Search Tree index that rejects rows whose ranges overlap; here it forbids two non-cancelled appointments for one technician from overlapping in time. |
| (5) | calendar outbox | A table that records pending Google Calendar operations in the same transaction as the appointment change (the transactional-outbox pattern), drained later by a background dispatcher so a calendar outage never loses a booking. |
