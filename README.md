# Field Service Management

A platform for service agencies (think elevator or appliance maintenance) that runs the whole job
lifecycle from a single source of truth. The full vision spans five pieces:

- **Back office** — customers, sites, and contacts; an asset catalog with per-device fault history; a
  scheduling dashboard tracking every call open → assigned → en route → in progress → done.
- **Technician field app** — daily route and navigation, check-in/out with time logging, digital
  service reports (checklists, notes, before/after photos) and an on-screen signature that
  auto-generates a signed PDF — all usable offline and syncing when the network returns.
- **Customer chat app** — a WhatsApp-style bot to open a call (pick the asset, describe the problem,
  attach a photo), self-service status, live "technician on the way" alerts, and signed-report download.
- **Backend** — role-based access (admin, dispatch, technician, customer), push/SMS/email
  notifications, PDF generation, and advanced search across customers, technicians, and assets.
- **Integrations & integrity** — two-way calendar sync, maps/navigation, cloud document storage, plus
  GPS verification, mandatory photo evidence, full audit trail, and parts/inventory control.

**Full product scope** is captured in the [vision document](https://docs.google.com/document/d/1bX7L_CL6hBIfpJVCkpRFYk6hIZ7OxD7dSugnPWCKLsY/edit),
  from which the five pieces above are summarized.

The platform is built **slice by slice**, each module getting its own design → plan → implementation cycle.

**Slice 1 — Scheduling** — is **feature-complete:** it delivers the calendar-and-booking core of that
vision. Google OIDC sign-in with roles, one-click technician calendar connect, customer self-booking
with a database-enforced no-double-booking guarantee, two-way Google Calendar sync (outbound
projection + inbound reconcile), central holiday exclusions, per-technician working hours and time
off, and in-app + email/.ics notifications (`.ics` = a calendar-invite attachment the recipient can
add to their own calendar). Google, email, and holiday integrations are driven by environment
variables and degrade gracefully when unset.

## Overview

- **Backend** (`backend/`): Python 3.12+, FastAPI, SQLAlchemy 2.x + PostgreSQL, Alembic.
- **Frontend** (`frontend/`): a modular React (Vite + TypeScript) app for sign-in, opening a service
  call, picking a slot, and editing appointments; served by the API at `/` when built.
- **Source of truth** is the Postgres database; external systems (Google Calendar) are downstream
  projections reached through ports, never imported by the core.

## Architecture

A **modular monolith** organized as bounded contexts under a single `fsm` package, following
ports-and-adapters (hexagonal) design:

| Context | Responsibility |
|---|---|
| `scheduling` | service calls, appointments, availability, lifecycle — the core domain (no external I/O) |
| `identity` | Google OIDC sign-in, users, roles |
| `calendar` | Google Calendar adapter behind `CalendarPort` (connect, free/busy, projection, inbound sync, holidays) |
| `notifications` | in-app feed + email/.ics behind `NotificationPort` |
| `platform` | composition root: configuration, database, web wiring, background workers |

The inner layers (`domain`, `application`, `ports`) depend only on abstractions and the standard
library; only `adapters` touch infrastructure. These boundaries are **enforced in CI** by
import-linter — a forbidden import fails the build, not just code review.

## Getting started

Prerequisites: **Python**, **Docker** (for PostgreSQL), and **Node.js + npm** (to build the React
frontend, which the API serves at `/`).

### 1. Configure (`backend/.env`)

```bash
./scripts/init-env.sh   # writes backend/.env from backend/.env.example, generating FSM_TOKEN_KEY + SESSION_SECRET
```

Configuring the **Google Cloud Console** OAuth client is mandatory. Google is the only sign-in path,
and every booking and scheduling action requires a signed-in session, so the app does nothing useful
until it is set. `init-env.sh` handles the rest of the baseline — `DATABASE_URL`/`APP_ENV` default to
the bundled Docker Postgres and the two local secrets are generated for you. Holidays and email are
the only features that stay disabled, without error, when left unset.

Each key — what it does, when it is required, and how to obtain it — is documented inline in
[`backend/.env.example`](backend/.env.example), which also contains the Google Cloud Console setup
steps. Refer to it there rather than duplicating the list here.

### 2. Run it

One launcher, **one** `backend/.env`, two run modes that reach the roles at the **same URLs**, each
completing Google sign-in. Docker is the default (a closer-to-production stack); `--host` runs the
roles as local uvicorn processes for fast boot and debugger attach. Either way PostgreSQL and Redis
run in Docker.

```bash
# DOCKER mode (default): roles run as containers; nginx publishes one localhost port per role
./scripts/start.sh                   # all roles: db + redis + migrations + backends + nginx
./scripts/start.sh technician        # one role (alias tec) -> http://localhost:8001

# HOST mode (--host): each role is a local uvicorn process on the same ports
./scripts/start.sh --host                # all roles            -> :8001 / :8002 / :8003
./scripts/start.sh technician --host     # one role (alias tec) -> http://localhost:8001
```

The launcher is idempotent and requires `backend/.env` (step 1) — it aborts with instructions if
that file is missing. Docker mode builds the backend image and brings the roles up as compose
services; `--host` provisions the virtualenv, builds the frontend, and runs one uvicorn per role.
Each mode starts PostgreSQL and Redis via Docker and applies migrations first. Edit `backend/.env`
and re-run to pick up changes. In either mode every role serves its React UI at `/`, API docs at
`/docs`, and `/health` + `/ready` for liveness and readiness. Bring the stack down or tail logs with
`./scripts/docker-helper.sh --stop` / `--logs`.

#### Open a UI in your browser

Each role is reached on its own `localhost` port — the same in either mode. In Docker mode nginx
serves the SPA and proxies the API per port; in host mode the uvicorn process serves the SPA and API
directly.

| App | URL |
|---|---|
| Technician | http://localhost:8001 |
| Customer | http://localhost:8002 |
| Back office | http://localhost:8003 |

### Google sign-in

Google is the only sign-in path, and every booking and scheduling action needs a signed-in session.
Google completes a sign-in only on a host whose callback URL is registered on the OAuth client, and
it accepts a loopback redirect URI only as bare `localhost`/`127.0.0.1` with a port — not a
`*.localhost` subdomain. So each role signs in on its own `localhost` port, and you register these
four callbacks (see `backend/.env.example`):

```
http://localhost:8001/auth/google/callback
http://localhost:8002/auth/google/callback
http://localhost:8003/auth/google/callback
http://localhost:8001/calendar/connect/callback     ← technician calendar connect
```

The app derives the callback from the host each request arrives on, so the role process that started
the sign-in also completes it: sign in at `http://localhost:8003` and you land there as admin. This
works identically in either mode. A production deployment fronts the roles by hostname over `https`
and registers those `https://…` callbacks instead.

## Testing

Run the whole suite — backend (unit, integration, API, contract, and architecture tests) plus the
frontend gates (typecheck, lint, build):

```bash
./scripts/test.sh            # everything; pass `backend` or `frontend` to scope it
```

Backend integration tests use ephemeral PostgreSQL via testcontainers, so Docker must be running. See
[docs/testing.md](docs/testing.md) for the test taxonomy.

## Documentation

- [Testing](docs/testing.md) — the test taxonomy (unit, integration, API, contract, architecture)
  and how to run it.
