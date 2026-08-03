"""Application factory and composition root."""
from __future__ import annotations

import asyncio
import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Callable

from fastapi import FastAPI
from fastapi.responses import HTMLResponse, JSONResponse
from sqlalchemy import text
from sqlalchemy.orm import Session, sessionmaker

from fsm.assist.domain.errors import AssistError
from fsm.core.events import build_event_bus
from fsm.platform.api.assist_errors import handle_assist_error
from fsm.platform.api.auth_routes import router as auth_router
from fsm.platform.api.backoffice_routes import router as backoffice_router
from fsm.platform.api.calendar_routes import router as calendar_router
from fsm.platform.api.events_routes import router as events_router
from fsm.platform.api.kb_routes import router as kb_router
from fsm.platform.api.scheduling_routes import handle_scheduling_error
from fsm.platform.api.scheduling_routes import router as scheduling_router
from fsm.platform.api.triage_routes import router as triage_router
from fsm.platform.assist_factory import build_chat_model, build_kb_index, build_photo_store
from fsm.platform.logging import configure_logging
from fsm.platform.roles import SERVING_ROLES
from fsm.scheduling.domain.errors import SchedulingError
from fsm.shared.constants import BRAND


def create_app(
    session_factory: Callable[[], Session] | sessionmaker[Session] | None = None,
    settings=None,
) -> FastAPI:
    """Compose the process FSM_ROLE selects: its routes, landing page, /health and /ready.

    session_factory: SQLAlchemy session factory injected for testing. When absent,
    the factory is built lazily from the process-wide settings on the first /ready call.
    settings: Settings instance injected for testing. When absent, loaded from environment.
    """
    configure_logging()

    if settings is None:
        from fsm.platform.config import get_settings
        settings = get_settings()

    role = settings.fsm_role
    if role not in SERVING_ROLES:
        raise ValueError(
            f"FSM_ROLE is {role!r}; expected one of {sorted(SERVING_ROLES)}. Serving with an "
            "unrecognized role would sign every user in through the customer funnel."
        )

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        """Capture the serving loop, which is what carries publishes raised off the request path."""
        app.state.event_loop = asyncio.get_running_loop()
        yield

    app = FastAPI(title=f"{BRAND} ({role})", lifespan=lifespan)
    app.state.session_factory = session_factory
    # Starlette types handlers as taking the Exception base, but it only invokes this one with
    # the SchedulingError instances it is registered for.
    app.add_exception_handler(SchedulingError, handle_scheduling_error)  # type: ignore[arg-type]
    app.add_exception_handler(AssistError, handle_assist_error)  # type: ignore[arg-type]
    app.include_router(scheduling_router)
    app.include_router(auth_router)
    app.include_router(calendar_router)
    app.include_router(backoffice_router)
    app.include_router(events_router)
    app.include_router(kb_router)
    app.include_router(triage_router)

    app.state.settings = settings
    app.state.event_bus = build_event_bus(settings.redis_url)
    app.state.kb_index = build_kb_index(settings)
    app.state.photo_store = build_photo_store(settings)
    app.state.assist_chat_model = build_chat_model(settings, app.state.photo_store)

    if settings.session_secret:
        from starlette.middleware.sessions import SessionMiddleware
        app.add_middleware(
            SessionMiddleware,
            secret_key=settings.session_secret.get_secret_value(),
            https_only=settings.app_env not in ("local", "test"),
        )

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
        from fsm.core.db import session_factory
        from fsm.platform.config import get_settings
        from fsm.platform.db import create_engine_from_settings

        engine = create_engine_from_settings(get_settings())
        app.state.session_factory = session_factory(engine)
    return app.state.session_factory


def _landing_html(role: str) -> str:
    """Minimal role-aware landing page linking to the API docs and health endpoints."""
    return f"""<!doctype html>
<html lang="en">
<head><meta charset="utf-8"><title>FSM — {role}</title></head>
<body style="font-family: system-ui, sans-serif; max-width: 40rem; margin: 4rem auto;">
  <h1>{BRAND}</h1>
  <p>Role: <strong>{role}</strong></p>
  <ul>
    <li><a href="/docs">Interactive API documentation</a></li>
    <li><a href="/health">Liveness (/health)</a></li>
    <li><a href="/ready">Readiness (/ready)</a></li>
  </ul>
</body>
</html>"""
