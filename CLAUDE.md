# CLAUDE.md

Field Service Management: a FastAPI modular monolith (package `fsm` in `backend/src`) that runs as
a process per role (technician, customer, back office) plus a calendar worker, behind an nginx edge
that serves the React page in `frontend/` on a port per role. Layout, layers and parts:
docs/architecture.md. It is a Docker Compose repo, aligned with loan-simulator, the group's
reference repo. The checkout belongs on the WSL ext4 filesystem, not under `/mnt/c`;
docs/development.md explains the cost.

## Operations scripts (scripts/)

Every script sources `scripts/common.sh`, which exports the three settings files under
`scripts/lib/` before it calls Compose: the committed `stack-params.sh`, and the gitignored
`params.sh` and `secrets.sh`, each beside an `.example.sh` that documents its keys. A bare
`docker compose` call therefore has no settings. `.githooks/pre-commit` refuses a commit that
stages one of the gitignored files, a value of `secrets.sh`, or an address of `params.sh` other
than `LICENSE_CONTACT`, the address the README and `NOTICE` give for a commercial license
(`PUBLISHED_SETTINGS` of `lib/settings-guard.sh`).

- Compose hands every backend process the same list of keys, once in `x-backend-env`, and
  overrides `DATABASE_URL`, `REDIS_URL` and `MINIO_ENDPOINT` with the in-network addresses, so
  the files hold the host forms. A backend process on the host runs from the repo root, because
  `Settings` reads the settings files by their path from the working directory; pytest runs from
  `backend/`, where it finds none.
- Nothing is bind-mounted, so the same Compose file runs against the EC2 instance's daemon: the
  edge image (`nginx/Dockerfile`) bakes in `nginx/` and the built page, and the data lives in the
  `fsm_pgdata` and `fsm_objectstore` volumes. An nginx edit takes a `deploy.sh` run.
- On EC2 each role is a stack of its own (`EC2_STACK-tech`, `-app`, `-admin`), because the shared
  `template-ec2.yaml` takes one origin port per stack and the roles are told apart by origin.
  `select_ec2_role` of `common.sh` points `lib/ec2.sh` at each in turn; an exported `STACK_NAME`
  is refused. `docker-compose.ec2.yml` sets each role's Google callbacks from its CloudFront
  address (`EC2_<ROLE>_URL`), since CloudFront reaches the edge over plain HTTP.
- The layer rules, enforced by `lint-imports` from `backend/pyproject.toml`: contexts (`assist`,
  `identity`, `scheduling`, `google_calendar`, `notifications`) never import each other; each is
  `adapters → application → ports → domain`; only `platform` composes them, and `core` imports
  nothing of the product.
- `FSM_TOKEN_KEY` of `secrets.sh` encrypts the stored calendar refresh tokens; a new one makes
  every stored connection unreadable, so `init-env.sh --force` is for a fresh start only.
- Before any AWS work, read this account's inventory, the
  `aws-account-inventory-<account ID>.md` under `/mnt/c/Projects/-- docs --/` that lists
  loan-simulator: the instance belongs to that repo's stack, and this repo's stacks are guests.
- `test.sh [all|backend|frontend|e2e]` (aliases `be`, `fe`) — the whole quality gate: bash
  syntax check and the shell tests of `scripts/tests/`, ruff, mypy, import-linter and pytest for
  `backend/`; oxlint, Vitest, `tsc` and the Vite build for `frontend/`. `e2e` is opt-in: the
  cross-process event sample under `samples/redis_event_bus_with_sse/`.
- `init-env.sh [--force]` — creates each missing gitignored `scripts/lib/secrets.sh`,
  `params.sh` and `aws-config.sh` from its `.example.sh`, with a generated database password,
  session secret, token key and store key; an existing file is kept unless `--force` is given.
- `deploy.sh` — runs `init-env.sh` first and stops on a list of every required setting still
  blank, then builds and runs Postgres (with its schema migration), Redis, the object store, the
  role replicas, the worker and the nginx edge in Docker Compose, and returns once each role
  answers on 8001, 8002 and 8003; `--ec2` does it on the loan-simulator stack's EC2 instance, as
  three guest stacks behind their own CloudFront distributions (`template-ec2.yaml`,
  `docker-compose.ec2.yml`), in the account of the gitignored `lib/aws-config.sh`.
- `docker-helper.sh [--ec2]` — `--stop [--volumes]`, `--logs [-e|-w] [--grep <pattern>]
  [--since <duration>] [--sorted] [service...]`, `--ps`; `--ec2 --delete-stack` deletes this
  repo's three EC2 stacks.
- `lib/ec2.sh` — the EC2 target: a stack's deploy, SSH with an Instance Connect key, Compose
  against the instance's daemon. `lib/settings-guard.sh` — the checks behind the pre-commit
  hook. Both are the same files in every Docker Compose repo.
- `tools/sql-helper.sh [--ec2]` — psql on the stack's database; `--counts`, `--rows`,
  `--backup <file>`, `--restore <file>`.
- `tools/lock.sh` — recompiles `backend/requirements.txt` inside the Dockerfile's Python image
  after editing the dependency list.
- `tools/release.sh [--minor|--major]` — tags the next version and pushes the tag; CI publishes
  the release.
