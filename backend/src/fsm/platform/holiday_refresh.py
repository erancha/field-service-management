"""Refresh job: fetch public holidays from Google Calendar and cache them locally.

Run as a one-shot job:

    python -m fsm.platform.holiday_refresh

No-op when google_api_key or holiday_calendar_id is unset. On fetch failure,
logs a warning and returns 0 — the existing cache is preserved (graceful degradation).
"""
from __future__ import annotations

import logging
from datetime import date

_log = logging.getLogger(__name__)


def refresh_holidays(
    session_factory,
    settings,
    *,
    reader_factory=None,
    today: date | None = None,
) -> int:
    """Fetch and cache public holidays; return the count upserted.

    Returns 0 without error when credentials are not configured or when the
    Google fetch fails (existing cache stays intact).
    """
    if reader_factory is None:
        from fsm.calendar.adapters.holiday_reader import build_holiday_reader
        reader_factory = build_holiday_reader

    if not settings.google_api_key or not settings.holiday_calendar_id:
        _log.info("Holiday refresh skipped: google_api_key or holiday_calendar_id not configured")
        return 0

    if today is None:
        today = date.today()

    years_ahead = settings.holiday_refresh_years_ahead
    time_max = date(today.year + years_ahead, today.month, today.day)

    try:
        api_key = settings.google_api_key.get_secret_value()
        reader = reader_factory(api_key)
        raw = reader.list_holidays(settings.holiday_calendar_id, today, time_max)
    except Exception:
        _log.warning(
            "Holiday fetch failed; serving cached holidays",
            exc_info=True,
        )
        return 0

    from fsm.scheduling.adapters.holiday_repository import SqlAlchemyHolidayRepository
    from fsm.scheduling.domain.holiday import Holiday

    holidays = [Holiday(date=d, name=name) for d, name in raw]

    with session_factory() as session:
        with session.begin():
            repo = SqlAlchemyHolidayRepository(session)
            repo.upsert_many(holidays)

    return len(holidays)


if __name__ == "__main__":
    from fsm.platform.config import get_settings
    from fsm.platform.db import create_engine_from_settings, session_factory
    from fsm.platform.logging import configure_logging

    configure_logging()
    _settings = get_settings()
    _engine = create_engine_from_settings(_settings)
    _factory = session_factory(_engine)
    count = refresh_holidays(_factory, _settings)
    _log.info("Upserted %d holidays", count)
