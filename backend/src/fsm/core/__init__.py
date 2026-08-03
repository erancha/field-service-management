"""App-agnostic backend plumbing: structured logging, engine construction, and an event bus.

Nothing here knows what this product is. Every module takes the product's choices — the
environment prefix its log levels are read from, the database URL and pool sizing, the broker
URL — as arguments, so the same code serves any backend process. The composition root in
fsm.platform supplies them and owns the reasoning behind each value.

An import-linter contract in backend/pyproject.toml holds the boundary: fsm.core may not import
any bounded context, the shared kernel, fsm.platform, or the web framework.
"""
