"""Google OAuth 2.0 endpoint URIs, defined once for every consumer.

Lives at platform level (not under platform.api) so calendar adapters can share the token
endpoint without depending on the web layer.
"""
from __future__ import annotations

GOOGLE_AUTH_URI = "https://accounts.google.com/o/oauth2/auth"
GOOGLE_TOKEN_URI = "https://oauth2.googleapis.com/token"
