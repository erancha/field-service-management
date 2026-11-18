#!/usr/bin/env bash
# Secrets of the Compose stack. ./scripts/init-env.sh copies this file to lib/secrets.sh
# (gitignored) and fills in the generated values; fill in the rest there and never commit it.
# Every line is a plain export KEY="value": the scripts source the file, and a backend process
# started on the host reads it too.

# Required: the password of POSTGRES_USER, set when the database volume is first created; changing
# it later needs --volumes on the stop (docker-helper.sh) or ALTER USER. init-env.sh writes a
# generated value.
export POSTGRES_PASSWORD=""

# Required: the database in SQLAlchemy form, as the host reaches it (DB_HOST_PORT of
# stack-params.sh). Compose replaces it with the in-network address (db:<DB_PORT>). init-env.sh
# writes it with the generated POSTGRES_PASSWORD.
export DATABASE_URL=""

# Required: signs the session cookie the sign-in flow depends on; blank, no session is kept and
# no one can sign in. init-env.sh writes a generated value.
export SESSION_SECRET=""

# Required: the Fernet key that encrypts the technicians' stored Google refresh tokens, so it gates
# connecting a calendar. Keep it stable: a new key makes every stored calendar connection
# unreadable. init-env.sh writes a generated value.
export FSM_TOKEN_KEY=""

# Required: the secret key of the photo store, which compose also gives the store itself with
# MINIO_ACCESS_KEY of stack-params.sh. init-env.sh writes a generated value.
export MINIO_SECRET_KEY=""

# Required: the secret of the Google OAuth client whose id is GOOGLE_CLIENT_ID of params.sh. Fill
# in by hand (docs/sign-in.md).
export GOOGLE_CLIENT_SECRET=""

# Optional: the provider API keys of the assistant's models (ASSIST_MODEL and ASSIST_EMBEDDINGS of
# params.sh). A model whose provider has no key here is off: embeddings are OpenAI's only, so the
# knowledge base needs OPENAI_API_KEY; the triage chat needs the key of ASSIST_MODEL's provider.
export ANTHROPIC_API_KEY=""
export OPENAI_API_KEY=""

# Optional: the SMTP account's password (for Gmail a 16-character App Password); blank, booking
# notifications stay in the in-app feed. SMTP_HOST and SMTP_USER are in params.sh.
export SMTP_PASS=""

# Optional: a Google Cloud API key restricted to the Google Calendar API, which reads the public
# holiday calendar HOLIDAY_CALENDAR_ID of stack-params.sh; blank, availability ignores holidays.
export GOOGLE_API_KEY=""
