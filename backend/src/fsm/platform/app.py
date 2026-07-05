"""Application factory and composition root."""
from __future__ import annotations

import os
import threading
from pathlib import Path
from typing import Callable

from fastapi import FastAPI
from fastapi.responses import HTMLResponse, JSONResponse
from sqlalchemy import text
from sqlalchemy.orm import Session, sessionmaker

from fsm.platform.api.auth_routes import router as auth_router
from fsm.platform.api.backoffice_routes import router as backoffice_router
from fsm.platform.api.calendar_routes import router as calendar_router
from fsm.platform.api.events_routes import router as events_router
from fsm.platform.api.scheduling_routes import handle_scheduling_error
from fsm.platform.api.scheduling_routes import router as scheduling_router
from fsm.platform.events import build_event_bus
from fsm.platform.logging import configure_logging
from fsm.scheduling.domain.errors import SchedulingError


def create_app(
    session_factory: Callable[[], Session] | sessionmaker[Session] | None = None,
    settings=None,
) -> FastAPI:
    """Build the FastAPI application and register the landing, /health, and /ready endpoints.

    session_factory: SQLAlchemy session factory injected for testing. When absent,
    the factory is built lazily from the process-wide settings on the first /ready call.
    settings: Settings instance injected for testing. When absent, loaded from environment.
    """
    configure_logging()
    role = os.environ.get("FSM_ROLE", "unknown")
    app = FastAPI(title=f"Field Service Management ({role})")
    app.state.session_factory = session_factory
    app.add_exception_handler(SchedulingError, handle_scheduling_error)
    app.include_router(scheduling_router)
    app.include_router(auth_router)
    app.include_router(calendar_router)
    app.include_router(backoffice_router)
    app.include_router(events_router)

    if settings is None:
        from fsm.platform.config import get_settings
        settings = get_settings()
    app.state.settings = settings
    app.state.event_bus = build_event_bus(settings)

    if settings.session_secret:
        from starlette.middleware.sessions import SessionMiddleware
        app.add_middleware(
            SessionMiddleware,
            secret_key=settings.session_secret.get_secret_value(),
            https_only=settings.app_env not in ("local", "test"),
        )

    if settings.fsm_dispatch_enabled:
        from fsm.platform.dispatcher_runner import run_forever

        # Resolve the factory the same way request handlers do: use the injected one
        # under test, otherwise build it lazily from settings. Gating on the flag alone
        # (not on an injected factory) is what makes the dispatcher actually run under
        # uvicorn --factory, where create_app receives no session_factory.
        dispatch_session_factory = _get_session_factory(app)

        stop_event = threading.Event()
        app.state.dispatcher_stop_event = stop_event

        thread = threading.Thread(
            target=run_forever,
            args=(dispatch_session_factory, settings, stop_event),
            daemon=True,
            name="fsm-dispatcher",
        )
        thread.start()

        @app.on_event("shutdown")
        def _stop_dispatcher() -> None:
            stop_event.set()

    if settings.fsm_sync_enabled:
        from fsm.platform.sync_runner import run_forever as sync_run_forever

        sync_session_factory = _get_session_factory(app)

        sync_stop_event = threading.Event()
        app.state.sync_stop_event = sync_stop_event

        sync_thread = threading.Thread(
            target=sync_run_forever,
            args=(sync_session_factory, settings, sync_stop_event),
            daemon=True,
            name="fsm-sync",
        )
        sync_thread.start()

        @app.on_event("shutdown")
        def _stop_sync() -> None:
            sync_stop_event.set()

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/ready")
    def ready() -> JSONResponse:
        factory = _get_session_factory(app)
        try:
            with factory() as session:
                session.execute(text("SELECT 1"))
            return JSONResponse({"status": "ready"}, status_code=200)
        except Exception:
            return JSONResponse({"status": "not ready"}, status_code=503)

    # Serve the built React app at "/" when FSM_FRONTEND_DIST points at a build output;
    # mounted last so the API routes above take precedence. Without it, "/" falls back to
    # a minimal role-aware landing page (dev and test default).
    _serve_root(app, role)

    return app


def _serve_root(app: FastAPI, role: str) -> None:
    dist = os.environ.get("FSM_FRONTEND_DIST")
    if dist and (Path(dist) / "index.html").is_file():
        from fastapi.staticfiles import StaticFiles

        app.mount("/", StaticFiles(directory=dist, html=True), name="frontend")
        return

    @app.get("/", response_class=HTMLResponse)
    def index() -> str:
        return _landing_html(role)


def _get_session_factory(
    app: FastAPI,
) -> Callable[[], Session] | sessionmaker[Session]:
    """Return the session factory stored on the app, building it lazily if absent."""
    if app.state.session_factory is None:
        from fsm.platform.config import get_settings
        from fsm.platform.db import create_engine_from_settings, session_factory

        engine = create_engine_from_settings(get_settings())
        app.state.session_factory = session_factory(engine)
    return app.state.session_factory


def _landing_html(role: str) -> str:
    """Minimal role-aware landing page linking to the API docs and health endpoints."""
    return f"""<!doctype html>
<html lang="en">
<head><meta charset="utf-8"><title>FSM — {role}</title></head>
<body style="font-family: system-ui, sans-serif; max-width: 40rem; margin: 4rem auto;">
  <h1>Field Service Management</h1>
  <p>Role: <strong>{role}</strong></p>
  <ul>
    <li><a href="/docs">Interactive API documentation</a></li>
    <li><a href="/health">Liveness (/health)</a></li>
    <li><a href="/ready">Readiness (/ready)</a></li>
  </ul>
</body>
</html>"""
