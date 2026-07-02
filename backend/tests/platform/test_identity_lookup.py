"""Unit tests for the guarded identity lookup shared by platform wiring."""
from __future__ import annotations

import uuid


class _RaisingSession:
    """Stands in for a SQLAlchemy session whose get() always blows up."""

    def get(self, *args, **kwargs):
        raise RuntimeError("db down")


def test_load_user_returns_none_and_logs_error_on_lookup_failure(caplog) -> None:
    import logging

    from fsm.platform.identity_lookup import load_user

    user_id = uuid.uuid4()
    with caplog.at_level(logging.ERROR, logger="fsm.platform.identity_lookup"):
        assert load_user(_RaisingSession(), user_id) is None

    [record] = caplog.records
    assert str(user_id) in record.getMessage()
    assert record.exc_info is not None
