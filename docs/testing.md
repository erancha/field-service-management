# Testing

How the test suite is organized and how to run it.

## Running

```bash
./scripts/test.sh            # everything (backend + frontend)
./scripts/test.sh backend    # backend only  (alias: be)
./scripts/test.sh frontend   # frontend only (alias: fe)
```

Backend integration tests start ephemeral PostgreSQL containers via testcontainers, so **Docker must
be running**. On first run the script provisions the backend virtualenv and installs frontend
dependencies. The same gates run in CI (`.github/workflows/ci.yml`).

## Backend (`backend/tests`, pytest)

Tests mirror the source layout — one package per bounded context (`identity`, `scheduling`,
`calendar`, `notifications`, `platform`) — and fall into five kinds.

### Unit tests
Pure and in-memory, no external I/O. Domain and application layers (and ports, for the contexts that
define them) are exercised against in-memory fakes — e.g. `tests/scheduling/domain`,
`tests/identity/application`. They cover slot-generation math (including DST correctness), appointment
lifecycle transitions, the inbound reconciliation decision logic (last-write-wins, DB-as-authority),
and each application service's behavior. Fast and deterministic.

### Integration tests
Run against a **real PostgreSQL** instance started per test module via testcontainers
(`tests/<context>/adapters`). They verify the SQLAlchemy repositories, the Alembic migrations, and the
database-enforced invariants — most importantly the GiST `EXCLUDE` no-double-booking constraint, which
can only be proven against a real Postgres, not a fake.

### API tests
End-to-end HTTP tests (`tests/platform/api`) drive the FastAPI app through Starlette's `TestClient`
against real Postgres: opening service calls, availability (free/busy, holidays, days-off, and the
first-available technician pool), booking with `409` on overlap, the OAuth sign-in and calendar-connect
flows (with injected fakes standing in for Google so no network or credentials are needed), and
notification delivery into the in-app feed.

### Contract tests
`tests/contracts` runs one shared behavioral suite against **both** the in-memory fake and the real
adapter for a port — e.g. `CalendarPort` against `FakeCalendarPort` and the Google adapter backed by a
fake client. This keeps the fakes that unit tests rely on faithful to the real implementations.

### Architecture tests
`tests/test_architecture.py` runs import-linter's boundary contracts (also runnable directly as
`lint-imports`): the build fails if any bounded context imports across a forbidden boundary — for
example `scheduling` importing an adapter package or a Google library. `tests/test_packages.py` asserts
every package is importable. These encode the hexagonal boundaries as executable checks rather than
conventions.

## Frontend (`frontend`)

The React app's quality gates are **typecheck** (`tsc --noEmit`), **lint** (`oxlint`), and a
production **build** (`vite build`); `scripts/test.sh frontend` runs all three.

**OPEN — no JavaScript unit/component test runner is configured yet.** Adding one (e.g. Vitest +
React Testing Library for the API client, hooks, and components) is the next step for frontend
coverage.
