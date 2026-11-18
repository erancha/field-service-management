#!/usr/bin/env bash
# Settings of the Compose stack that are neither secret nor private, committed so every checkout
# runs the same stack. Sourced by scripts/common.sh, never executed; a backend process started on
# the host reads it too (backend/src/fsm/platform/config.py), so every setting is one plain export
# line with a quoted value, which may name a key set above it as ${KEY}. Secrets are in
# secrets.sh and this deployment's own settings in params.sh, both gitignored.
#
# Compose hands each container only the keys it reads, listed per service in docker-compose.yml.
# A commented-out line shows an optional key at its default; uncomment it to set the key.

# ── Ports ────────────────────────────────────────────────────────────────────────
# Read by docker-compose.yml only: the ports the edge publishes the three role apps on, on every
# interface of this machine: technician, customer and back office. Each role signs in on its own
# localhost port, the only loopback form Google accepts as a redirect URI, so each port is part
# of the Google client's redirect URIs (docs/sign-in.md). Each must be free on the host.
export EDGE_TECHNICIAN_HOST_PORT="8001"
export EDGE_CUSTOMER_HOST_PORT="8002"
export EDGE_BACKOFFICE_HOST_PORT="8003"
# Read by docker-compose.yml only: the port Postgres listens on inside its container.
export DB_PORT="5432"
# Read by docker-compose.yml only: the loopback port Postgres is published on, for a backend
# started on the host (DATABASE_URL of secrets.sh names it) or a psql on this machine. It must be
# free on the host.
export DB_HOST_PORT="5432"
# Read by docker-compose.yml only: the loopback ports Redis and the object store are published
# on, for a backend started on the host (REDIS_URL and MINIO_ENDPOINT below name them). The
# object store's stays off the S3 default 9000, so the stack runs beside another local S3 store.
export REDIS_HOST_PORT="6379"
export OBJECT_STORE_HOST_PORT="9100"

# ── EC2 ──────────────────────────────────────────────────────────────────────────
# Read by scripts/lib/ec2.sh only, for deploy.sh --ec2. Each role has a stack of its own, named
# EC2_STACK-tech, EC2_STACK-app and EC2_STACK-admin on main; any other branch adds -fb.
export EC2_STACK="field-service-management"
# The stacks are guests on the instance the loan-simulator stack owns, which must be deployed
# first from its own repo; each adds its role's port and a CloudFront distribution.
export EC2_HOST_STACK="loan-simulator"
# The port CloudFront reaches a stack at on the instance is its role's edge port above, which
# select_ec2_role of scripts/common.sh sets as EC2_ORIGIN_PORT before each stack's deploy.

# ── Database ─────────────────────────────────────────────────────────────────────
# Read by docker-compose.yml only: the Postgres user and database the tables live in; also read
# by init-env.sh and tools/sql-helper.sh, and set when the database volume is first created.
export POSTGRES_USER="fsm"
export POSTGRES_DB="fsm"

# ── Environment ──────────────────────────────────────────────────────────────────
# local, test, staging or prod. Outside local and test the session cookie is marked Secure;
# docker-compose.ec2.yml sets prod for the EC2 instance behind CloudFront.
# export APP_ENV="local"
# The IANA timezone of the one service region; appointment times are shown in it.
# export TIMEZONE="Asia/Jerusalem"

# ── Live events ──────────────────────────────────────────────────────────────────
# The Redis that carries live events between the role processes, as a backend started on the
# host reaches it. Compose replaces it with the in-network address (redis://redis:6379/0). Unset,
# a process falls back to an in-process bus that reaches only its own streams.
export REDIS_URL="redis://localhost:${REDIS_HOST_PORT}/0"

# ── Photo storage ────────────────────────────────────────────────────────────────
# The S3-compatible store of the photos customers attach in the triage chat, as a backend started
# on the host reaches it. Compose replaces it with the in-network address (objectstore:9000).
export MINIO_ENDPOINT="localhost:${OBJECT_STORE_HOST_PORT}"
# The store's access key, which compose also gives the store itself; its secret key is
# MINIO_SECRET_KEY of secrets.sh. The store is reachable from this machine's loopback interface
# and the Compose network only.
export MINIO_ACCESS_KEY="fsm"
# export MINIO_BUCKET="fsm-photos"
# export MINIO_SECURE="false"

# ── Calendar loops ───────────────────────────────────────────────────────────────
# The public base address of the technician app: the worker writes photo links into calendar
# events from it, and refuses to start without it. docker-compose.ec2.yml sets the technician
# stack's CloudFront address for the EC2 instance.
export TECHNICIAN_APP_URL="http://localhost:${EDGE_TECHNICIAN_HOST_PORT}"
# How often the dispatcher pushes confirmed bookings from the outbox to Google, in seconds.
# export FSM_DISPATCH_INTERVAL_SECONDS="5.0"
# How often the poller asks Google for technician-side edits, and how long a worker that lost the
# poll lease waits before trying for it again, in seconds.
# export FSM_SYNC_INTERVAL_SECONDS="30.0"
# export FSM_SYNC_LEASE_RETRY_SECONDS="30.0"

# ── Sign-in callbacks ────────────────────────────────────────────────────────────
# Blank, each role derives its sign-in and calendar-connect callbacks from the address a flow
# began on, so each role completes Google's consent on its own port. docker-compose.ec2.yml sets
# them per role from the role's CloudFront address. Any value must be registered on the Google
# client.
# export GOOGLE_REDIRECT_URI=""
# export GOOGLE_CALENDAR_REDIRECT_URI=""

# ── Booking churn limit ──────────────────────────────────────────────────────────
# A customer who cancels FSM_BOOKING_CANCEL_LIMIT or more appointments within the window is
# blocked from booking until the cool-off has passed since their latest cancellation; 0 turns the
# check off.
# export FSM_BOOKING_CANCEL_LIMIT="3"
# export FSM_BOOKING_CANCEL_WINDOW_HOURS="24.0"
# export FSM_BOOKING_CANCEL_COOLOFF_HOURS="24.0"

# ── Public holidays ──────────────────────────────────────────────────────────────
# A public Google holiday calendar whose days availability leaves out, read with GOOGLE_API_KEY of
# secrets.sh; blank, availability ignores holidays. Ids have the form
# <language>.<region>#holiday@group.v.calendar.google.com.
# export HOLIDAY_CALENDAR_ID=""
# How many years ahead the holidays are cached.
# export HOLIDAY_REFRESH_YEARS_AHEAD="1"

# ── Email ────────────────────────────────────────────────────────────────────────
# The SMTP relay's port, and whether the connection upgrades to TLS; the host and account are in
# params.sh, the password in secrets.sh.
# export SMTP_PORT="587"
# export SMTP_USE_TLS="true"

# ── Logging ──────────────────────────────────────────────────────────────────────
# The root log level of every backend process, and per-module levels over it (none by default;
# the example traces live-event delivery). The logging setup reads both from the process
# environment, so compose passes them and a process started on the host takes them only when
# they are exported in its shell.
# export FSM_LOG_LEVEL="WARNING"
# export FSM_LOG_LEVELS="fsm.core.events=INFO,fsm.platform.api.events_routes=INFO"
