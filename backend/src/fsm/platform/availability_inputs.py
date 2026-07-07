"""Builds the booking-policy inputs resolver injected into inbound reconciliation.

Degrades rather than stalls: corrupt working hours fall back to the default schedule, and a
holiday or day-off read failure falls back to no exclusions — each logged — so a policy-data
problem can never stall the sync poller.

Working hours validate in the service-region timezone (Settings.timezone), the same zone the
slot routes offer availability in, so the hours checked here match the hours the offered slots
imply.
"""
from __future__ import annotations

import logging
import zoneinfo
from datetime import datetime, tzinfo
from typing import Callable
from uuid import UUID

from fsm.scheduling.adapters.holiday_repository import SqlAlchemyHolidayRepository
from fsm.scheduling.adapters.time_off_repository import SqlAlchemyTimeOffRepository
from fsm.scheduling.adapters.working_hours_repository import SqlAlchemyWorkingHoursRepository
from fsm.scheduling.domain.availability import AvailabilityInputs
from fsm.scheduling.domain.errors import SchedulingError
from fsm.scheduling.domain.working_hours import WeeklyWorkingHours

_log = logging.getLogger(__name__)


def build_availability_inputs(
    session_factory,
    settings,
) -> Callable[[UUID, datetime], AvailabilityInputs]:
    """Return a resolver mapping (technician_id, proposed start) to their policy inputs.

    The resolver owns the tz-then-local-date resolution: the exclusion window is the single
    local day the proposed start falls on, which is the only day is_available consults.
    Each call opens a short session, so the resolver is safe to hold across poll cycles.
    """
    tz: tzinfo = zoneinfo.ZoneInfo(settings.timezone)

    def _resolve(technician_id: UUID, proposed_start: datetime) -> AvailabilityInputs:
        with session_factory() as session:
            wh_repo = SqlAlchemyWorkingHoursRepository(session)

            try:
                working_hours = wh_repo.get_for_technician(technician_id)
            except SchedulingError:
                _log.warning(
                    "Corrupt stored working hours for technician %s; validating against the "
                    "default schedule",
                    technician_id,
                    exc_info=True,
                )
                working_hours = WeeklyWorkingHours.default()

            day = proposed_start.astimezone(tz).date()
            try:
                holidays = SqlAlchemyHolidayRepository(session).list_between(day, day)
            except Exception:
                _log.warning(
                    "Failed to load holidays for %s; validating without holiday exclusions",
                    day,
                    exc_info=True,
                )
                holidays = set()
            try:
                days_off = SqlAlchemyTimeOffRepository(session).list_between(
                    technician_id, day, day
                )
            except Exception:
                _log.warning(
                    "Failed to load days off for technician %s; validating without them",
                    technician_id,
                    exc_info=True,
                )
                days_off = set()

        return AvailabilityInputs(
            working_hours=working_hours,
            tz=tz,
            excluded_dates=frozenset(holidays | days_off),
        )

    return _resolve
