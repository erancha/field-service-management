"""Guards that backend/.env.example documents the shipped narrow-scope calendar design.

The example file is the repo's designated config reference, so it must not drift back to describing
the abandoned broad ``.../auth/calendar`` scope. These checks pin its calendar-scope prose to the
contract enforced by ``fsm.google_calendar.scopes``.
"""
import re
from pathlib import Path

from fsm.google_calendar.scopes import CALENDAR_OAUTH_SCOPES

ENV_EXAMPLE = Path(__file__).resolve().parents[2] / ".env.example"


def _env_example_text() -> str:
    return ENV_EXAMPLE.read_text(encoding="utf-8")


def _prose(text: str) -> str:
    """Comment prose with line-wrap artifacts removed, so substring checks survive re-wrapping."""
    unwrapped = re.sub(r"\n#\s*", " ", text)
    return re.sub(r"\s+", " ", unwrapped)


def test_documents_both_narrow_scopes():
    """Each granted scope's short name appears in the reference so operators know what to consent to."""
    text = _env_example_text()
    for scope in CALENDAR_OAUTH_SCOPES:
        short_name = scope.rsplit("/", 1)[1]
        assert short_name in text, f"{short_name} missing from .env.example"


def test_points_at_live_scope_module_not_stale_files():
    """The scope pointer names the current definition site and drops the relocated stale ones."""
    text = _env_example_text()
    assert "google_calendar/scopes.py" in text
    assert "client_factory.py" not in text
    assert "calendar_routes.py" not in text


def test_no_inverted_open_flag_for_shipped_design():
    """The narrow-scope design is shipped, so it must not be flagged as unimplemented."""
    prose = _prose(_env_example_text())
    assert "not yet implemented" not in prose


def test_console_step_does_not_instruct_ticking_broad_scope():
    """Console setup must align with docs/calendar-setup.md, which leaves the broad scope unticked."""
    prose = _prose(_env_example_text())
    assert "tick .../auth/calendar," not in prose
