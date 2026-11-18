#!/usr/bin/env bash
# Settings of this deployment that are its own and no secret. ./scripts/init-env.sh copies this
# file to lib/params.sh (gitignored); fill it in there. Every line is a plain export KEY="value":
# the scripts source the file, and a backend process started on the host reads it too.

# Required: the id of the Google OAuth web client every role signs in with, and technicians connect
# their calendars through. Fill in by hand (docs/sign-in.md); its secret is in secrets.sh.
export GOOGLE_CLIENT_ID=""

# The Google accounts granted the administrator role on their first sign-in at the back office,
# comma separated; the only way to that role, so blank leaves the back office closed to everyone.
export ADMIN_EMAILS=""

# Optional: provider:model of the triage chat's model (anthropic or openai) and of the knowledge
# base's embeddings (openai only), each off while blank or without its provider's key in
# secrets.sh. A new embeddings model needs every document re-indexed from the back office, since
# vectors of different models do not compare.
export ASSIST_MODEL="anthropic:claude-sonnet-5"
export ASSIST_EMBEDDINGS="openai:text-embedding-3-small"

# Optional: the SMTP relay and the account booking notifications are sent from, with an .ics
# invite; blank, notifications stay in the in-app feed. SMTP_FROM replaces the sender address
# when it must differ from the account. The password is in secrets.sh.
export SMTP_HOST=""
export SMTP_USER=""
export SMTP_FROM=""

# Optional: the address the README and NOTICE give for a commercial license, which
# backend/pyproject.toml publishes too. Tracked files may show this address; the pre-commit hook
# refuses any other address of this file.
export LICENSE_CONTACT=""
