"""Guards that docs/sign-in.md documents the shipped narrow-scope calendar design.

Its Google setup steps are what an operator follows to configure the OAuth client, so they must
not drift to describing the broad `.../auth/calendar` scope. These checks pin its calendar-scope
prose to the contract enforced by `fsm.google_calendar.scopes`.
"""
import re
from pathlib import Path

from fsm.google_calendar.scopes import CALENDAR_OAUTH_SCOPES

SIGN_IN_DOC = Path(__file__).resolve().parents[3] / "docs" / "sign-in.md"


def _sign_in_text() -> str:
    return SIGN_IN_DOC.read_text(encoding="utf-8")


def _prose(text: str) -> str:
    """Prose with line breaks removed, so substring checks survive re-wrapping."""
    return re.sub(r"\s+", " ", text)


def test_documents_both_narrow_scopes():
    """Each granted scope's short name appears, so operators know what to consent to."""
    text = _sign_in_text()
    for scope in CALENDAR_OAUTH_SCOPES:
        short_name = scope.rsplit("/", 1)[1]
        assert short_name in text, f"{short_name} missing from docs/sign-in.md"


def test_points_at_live_scope_module_not_stale_files():
    """The scope pointer names scopes.py, which defines the scopes, and no module that uses them."""
    text = _sign_in_text()
    assert "google_calendar/scopes.py" in text
    assert "client_factory.py" not in text
    assert "calendar_routes.py" not in text


def test_no_inverted_open_flag_for_shipped_design():
    """The narrow-scope design is shipped, so it must not be flagged as unimplemented."""
    prose = _prose(_sign_in_text())
    assert "not yet implemented" not in prose


def test_console_step_does_not_instruct_ticking_broad_scope():
    """Console setup aligns with docs/calendar-setup.md, which leaves the broad scope unticked."""
    prose = _prose(_sign_in_text())
    assert "tick .../auth/calendar," not in prose
