# Testing

How the test suite is organized and how to run it.

## Running

```bash
./scripts/test.sh                        # everything (backend + frontend)
./scripts/test.sh backend                # backend only  (alias: be)
./scripts/test.sh frontend               # frontend, full (alias: fe)
./scripts/test.sh frontend=unit          # frontend fast path: typecheck + vitest only (alias: fe=u)
./scripts/test.sh backend frontend=unit  # combine targets in one run
```

Each argument is a target with an optional `=mode`, and targets combine. The `=unit` mode applies to
the frontend only: it keeps the typecheck but skips oxlint and the vite build for a faster inner loop.

Backend integration tests start ephemeral PostgreSQL and MinIO containers via
testcontainers<sup>(1)</sup>, so **Docker must be running**. On first run the script provisions the
backend virtualenv and installs frontend dependencies. The same gates run in CI
(`.github/workflows/ci.yml`).

## Backend (`backend/tests`, pytest)

Before pytest, `scripts/test.sh backend` runs three static gates: **lint** (`ruff check src tests`),
**typecheck** (`mypy`, scoped to `src` — tests lean on fixtures and monkeypatching that static
analysis cannot follow), and the **import-linter** boundary contracts described under
[Architecture tests](#architecture-tests).

Tests mirror the source layout — one package per bounded context (`identity`, `scheduling`,
`google_calendar`, `notifications`, `assist`) plus `platform` — and fall into five kinds.

### Unit tests
Pure and in-memory, no external I/O. Domain and application layers (and ports, for the contexts that
define them) are exercised against in-memory fakes — e.g. `tests/scheduling/domain`,
`tests/identity/application`. They cover slot-generation math (including DST<sup>(2)</sup> correctness), appointment
lifecycle transitions, the inbound reconciliation decision logic (last-write-wins, DB-as-authority),
and each application service's behavior. Fast and deterministic.

### Integration tests
Run against a **real PostgreSQL** instance started per test module via testcontainers
(`tests/<context>/adapters`). They verify the SQLAlchemy repositories, the Alembic migrations, and the
database-enforced invariants — most importantly the GiST `EXCLUDE`<sup>(3)</sup> no-double-booking constraint, which
can only be proven against a real Postgres, not a fake. The assist context's `MinioPhotoStore`
adapter is verified the same way, round-tripping bytes against a real **MinIO** container
(`tests/assist/adapters/test_photo_store.py`).

### API tests
End-to-end HTTP tests (`tests/platform/api`) drive the FastAPI app through Starlette's `TestClient`
against real Postgres: opening service calls, availability (free/busy, holidays, days-off, and the
first-available technician pool), booking with `409` on overlap, the OAuth sign-in and calendar-connect
flows (with injected fakes standing in for Google so no network or credentials are needed), and
notification delivery into the in-app feed.

### Contract tests
`tests/contracts` runs one shared behavioral suite against **both** the in-memory fake and the real
adapter for a port, so the fakes the unit tests rely on cannot drift from the implementations they
stand in for: `CalendarPort` (`FakeCalendarPort` against the Google adapter backed by a fake client)
and `ServiceCallOpener` (`FakeServiceCallOpener` against the scheduling bridge).

### Architecture tests
`tests/test_architecture.py` runs import-linter's boundary contracts (also runnable directly as
`lint-imports`): the build fails if any bounded context imports across a forbidden boundary — for
example `scheduling` importing an adapter package or a Google library. `tests/test_packages.py` asserts
every package is importable. These encode the hexagonal<sup>(4)</sup> boundaries as executable checks rather than
conventions.

## Frontend (`frontend`)

The React app's quality gates are **typecheck** (`tsc --noEmit`), **lint** (`oxlint`),
**unit/component tests** (`vitest run`), and a production **build** (`vite build`);
`scripts/test.sh frontend` runs all four. `scripts/test.sh frontend=unit` runs just the typecheck and
vitest — the inner-loop shortcut, not a substitute for the full run before committing.

Tests live next to the code they cover as `*.test.ts(x)` and run under Vitest in a jsdom
environment with React Testing Library (per-test DOM cleanup is wired in `src/test/setup.ts`).
They cover the API client modules, the pure helpers (onboarding completeness, phone validation, error
shaping), the data-fetching and SSE hooks, and component/page behaviour up to whole role pages —
including the customer triage chat and its streaming decode, the back-office knowledge-base panel, the
booking flow, and the technician calendar connect/disconnect controls.

## Glossary

| Ref | Term | Meaning |
| --- | --- | --- |
| (1) | testcontainers | A library that starts throwaway Docker containers (here PostgreSQL) for the duration of a test module, giving integration tests a real database instead of a fake. |
| (2) | DST — Daylight Saving Time | Seasonal clock shifts that make some local days shorter or longer; slot-generation math is tested to stay correct across them. |
| (3) | GiST `EXCLUDE` | A PostgreSQL exclusion constraint backed by a Generalized Search Tree index; it enforces no-double-booking in the database and can only be verified against a real Postgres. |
| (4) | hexagonal (ports and adapters) | An architecture where the core domain talks only to abstract ports and all infrastructure lives in adapters behind them; the boundaries are checked in CI by import-linter. |
