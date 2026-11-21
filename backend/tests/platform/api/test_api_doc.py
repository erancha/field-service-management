"""docs/api.md names every HTTP route the app declares, and no route it does not.

The router is the source of truth: each APIRoute's methods and path, read from the app at run
time through iter_route_contexts, which resolves the routers the app includes into the routes
they declare, HEAD and OPTIONS left out. FastAPI's own documentation routes and the mounted page
are not APIRoutes, so they are not product routes and are not compared. The document names a
route in backticks as `METHOD /path`, the path exactly as the router declares it. The fixture
`app` is the only part of this file tied to this repository.
"""

import re
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.routing import APIRoute, iter_route_contexts

from fsm.platform.app import create_app
from fsm.platform.config import Settings
from fsm.platform.roles import SERVING_ROLES

HTTP_METHODS = ("GET", "POST", "PUT", "PATCH", "DELETE")
DOC_ROUTE = re.compile(r"`(" + "|".join(HTTP_METHODS) + r") (/[^`\s]*)`")
REPO = next(p for p in Path(__file__).resolve().parents if (p / "docs").is_dir())
API_DOC = REPO / "docs/api.md"


# Every role process the stack serves is one app, so each is compared against the document.
@pytest.fixture(params=SERVING_ROLES)
def app(request: pytest.FixtureRequest) -> FastAPI:
    return create_app(
        settings=Settings(
            database_url="postgresql+psycopg://fsm:fsm@localhost:5432/fsm",
            app_env="test",
            fsm_role=request.param,
        )
    )


def declared_routes(app: FastAPI) -> set[str]:
    declared: set[str] = set()
    for context in iter_route_contexts(app.routes):
        route = context.original_route
        if not isinstance(route, APIRoute):
            continue
        # An APIRoute declared with no method is a GET route, so the set is never absent.
        assert route.methods is not None
        methods = route.methods.intersection(HTTP_METHODS)
        declared.update(f"{method} {context.path}" for method in methods)
    return declared


def documented_routes(doc: str) -> set[str]:
    return {f"{m.group(1)} {m.group(2)}" for m in DOC_ROUTE.finditer(doc)}


def test_api_doc(app: FastAPI) -> None:
    declared = declared_routes(app)
    documented = documented_routes(API_DOC.read_text())
    missing = sorted(declared - documented)
    extra = sorted(documented - declared)
    problems = [f"undocumented in {API_DOC}: `{r}`" for r in missing]
    problems += [f"{API_DOC} names `{r}`, which no router declares" for r in extra]
    assert not problems, "\n".join(problems)
