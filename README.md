# Field Service Management

[![CI](https://github.com/erancha/field-service-management/actions/workflows/ci.yml/badge.svg)](https://github.com/erancha/field-service-management/actions/workflows/ci.yml)

A service-call management platform for agencies like elevator or appliance maintenance companies.

**Contents:** [Features & roadmap](#features--roadmap) · [Getting started](#getting-started) · [Scripts](#scripts) · [Testing](#testing) · [Architecture](#architecture) · [License](#license)

## Features & roadmap

[docs/features.md](docs/features.md) covers what's running today — sign-in and roles, booking and
scheduling, two-way Google Calendar sync, notifications, the customer's triage assistant and its
photo handling, the knowledge base, and deployment — plus the roadmap tracked in issues.

The [**visual walkthrough**](https://erancha.github.io/field-service-management/samples/walkthrough/)
shows most of that list actually running, without deploying anything: annotated screenshots from one
uninterrupted session, starting on an empty database and ending with a booked appointment in two
Google Calendars.

## Getting started

Prerequisites: **Python ≥3.12**, **Docker**, and **Node.js 22+ with npm**.

### 1. Configuration (`backend/.env`)

```bash
./scripts/init-env.sh   # writes backend/.env from backend/.env.example and mints the local secrets
```

Configuring the **Google Cloud Console** OAuth client is mandatory. Google is the only sign-in path,
and every booking and scheduling action requires a signed-in session, so the app does nothing useful
until it is set. `init-env.sh` handles the rest of the baseline: `DATABASE_URL`/`APP_ENV` default to
the bundled Docker Postgres, and the two secrets every install must mint locally — `SESSION_SECRET`
and `FSM_TOKEN_KEY` — are generated for you. Holidays and email are the only features that stay
disabled, without error, when left unset.

Every key in `backend/.env` — what it does, when it is required, and how to obtain it — is
documented inline in [`backend/.env.example`](backend/.env.example), which also contains the Google
Cloud Console setup steps. Refer to it there rather than duplicating the list here.

### 2. Runtime

The app runs as three role apps — technician, customer, and back office — each reached on its own
localhost port. One launcher, `./scripts/start.sh`, starts everything from the `backend/.env`
written in step 1 and offers two run modes; both serve the roles at the same URLs and support the
full Google sign-in flow. Docker mode (the default) is a closer-to-production stack; `--host` runs
the roles as local uvicorn processes for fast boot and debugger attach. Either way PostgreSQL and
Redis run in Docker.

```bash
# DOCKER mode (default): roles run as containers; nginx publishes one localhost port per role
./scripts/start.sh                   # all roles: db + redis + migrations + backends + nginx
./scripts/start.sh technician        # one role (alias tec) -> http://localhost:8001

# HOST mode (--host): each role is a local uvicorn process on the same ports
./scripts/start.sh --host                # all roles            -> :8001 / :8002 / :8003
./scripts/start.sh technician --host     # one role (alias tec) -> http://localhost:8001
```

The launcher is idempotent and aborts with instructions if `backend/.env` is missing. Docker mode
builds the backend image and brings the roles up as compose services; `--host` provisions the
virtualenv, builds the frontend, and runs one uvicorn per role. Each mode starts PostgreSQL and
Redis via Docker and applies migrations first. Edit `backend/.env` and re-run to pick up changes. In
either mode every role serves its React UI at `/`, API docs at `/docs`, and `/health` + `/ready` for
liveness and readiness. Bring the stack down or tail logs with `./scripts/docker-helper.sh --stop` /
`--logs`.

#### Open a UI in your browser

In Docker mode nginx serves the SPA and proxies the API per port; in host mode the uvicorn process
serves the SPA and API directly.

| App | URL |
|---|---|
| Technician | http://localhost:8001 |
| Customer | http://localhost:8002 |
| Back office | http://localhost:8003 |

## Scripts

All live in `scripts/`; run with `-h`/`--help` for full usage.

| Script | Purpose |
|---|---|
| `init-env.sh` | Bootstrap `backend/.env` on a fresh checkout. |
| `generate-secret.sh` | Generate one application secret; used by `init-env.sh`. |
| `start.sh` | Run the app. |
| `docker-helper.sh` | Operate the running Docker stack. |
| `sql-helper.sh` | Open psql against the database. |
| `test.sh` | Run the test suite — see [Testing](#testing). |
| `deploy-to-ec2/start.sh` | Serve the stack publicly from an EC2 box over HTTPS — see [its README](scripts/deploy-to-ec2/README.md). |

## Testing

Run the whole suite — backend (unit, integration, API, contract, and architecture tests) plus the
frontend gates (typecheck, lint, vitest unit/component tests, build):

```bash
./scripts/test.sh            # everything; pass `backend` or `frontend` to scope it
```

Backend integration tests use ephemeral PostgreSQL via testcontainers, so Docker must be running. See
[docs/testing.md](docs/testing.md) for the test taxonomy.

## Architecture

The backend is a **modular monolith**: bounded contexts (`assist`, `identity`, `scheduling`,
`google_calendar`, `notifications`) under a single `fsm` package, each layered ports-and-adapters
style and composed by `fsm.platform`. Contexts never import each other — each declares the ports it
needs and `platform` injects implementations that bridge to the others.
[docs/architecture.md](docs/architecture.md) picks up from here:

- each package's responsibility, the full import-rule diagram, the context-integration pattern, and
  how CI enforces the rules with import-linter
- authentication & live communication — Google OIDC sign-in, role-scoped sessions, and SSE updates
  fanned out over Redis pub/sub
- the database schema — PostgreSQL as the source of truth, database-enforced no-double-booking, and
  the transactional outbox behind the two-way Google Calendar sync

### Tech stack

- **Backend** (`backend/`): Python 3.12+, FastAPI, SQLAlchemy 2.x + PostgreSQL, Alembic.
- **Frontend** (`frontend/`): a modular React (Vite + TypeScript) app.

## License

Released under the MIT License. See [LICENSE](LICENSE).

---

More projects by the author: [github.com/erancha](https://github.com/erancha)
