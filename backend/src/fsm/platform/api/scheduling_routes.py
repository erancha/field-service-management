"""FastAPI router for scheduling endpoints.

Wiring: each request opens a SqlAlchemyUnitOfWork, runs the use case, calls
commit(), then closes the UoW. Domain exceptions escape the handlers and are
mapped to HTTP responses by handle_scheduling_error, which create_app registers
as the app-level handler for SchedulingError.

Domain error mapping:
- SlotUnavailable / InvalidTransition → 409 Conflict
- NotFoundError                       → 404 Not Found
- InvalidTimeRange                    → 400 Bad Request
- IncompleteContactInfo               → 422 Unprocessable Entity
"""
from __future__ import annotations

import zoneinfo
from datetime import date, datetime, timedelta, timezone
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import JSONResponse

from fsm.scheduling.application.appointment_service import AppointmentService
from fsm.scheduling.application.service_call_service import ServiceCallService
from fsm.scheduling.domain.errors import (
    IncompleteContactInfo,
    InvalidTimeRange,
    InvalidTransition,
    NotFoundError,
    SchedulingError,
    SlotUnavailable,
)
from fsm.scheduling.domain.time_range import TimeRange
from fsm.scheduling.domain.working_hours import DailyHours, WeeklyWorkingHours

from fsm.platform.api.schemas import (
    AddDetailsRequest,
    AppointmentResponse,
    AvailabilityResponse,
    BookAppointmentRequest,
    DailyHoursSchema,
    DayOffRequest,
    DaysOffResponse,
    OpenServiceCallRequest,
    PooledAvailabilityResponse,
    PooledSlotResponse,
    RescheduleRequest,
    ServiceCallResponse,
    SlotResponse,
    TimezoneRequest,
    TimezoneResponse,
    WorkingHoursRequest,
    WorkingHoursResponse,
)
from fsm.platform.calendar_resolver import build_calendar_resolver
from fsm.platform.config import DEFAULT_TIMEZONE
from fsm.platform.dev_adapters import LoggingNotificationPort, NullCalendarPort
from fsm.platform.identity_lookup import build_contact_resolver
from fsm.platform.notifications_factory import build_notifications
from fsm.platform.api.auth_deps import SessionUser, require_role, require_user
from fsm.identity.domain.role import Role

# Every scheduling route requires an authenticated session; identity is taken from the session,
# never from the request body. Per-route role and ownership are enforced in the handlers below.
router = APIRouter(prefix="/api", dependencies=[Depends(require_user)])


def _get_session_factory(request: Request):
    """Return the app's session factory, building it lazily from settings if absent."""
    from fsm.platform.app import _get_session_factory as _lazy_session_factory

    return _lazy_session_factory(request.app)


def _build_uow(request: Request):
    """Construct a SqlAlchemyUnitOfWork bound to the request's session factory."""
    from fsm.scheduling.adapters.unit_of_work import SqlAlchemyUnitOfWork

    factory = _get_session_factory(request)
    return SqlAlchemyUnitOfWork(factory)


import logging as _logging

_log = _logging.getLogger(__name__)


def _load_holidays(request: Request, uow, date_from, date_to) -> set:
    """Return cached holiday dates for the requested window.

    On any error, falls back to an empty set so availability never 500s
    due to a holiday-read failure.
    """
    try:
        from fsm.scheduling.adapters.holiday_repository import SqlAlchemyHolidayRepository

        repo = SqlAlchemyHolidayRepository(uow._session)
        return repo.list_between(date_from, date_to)
    except Exception:
        _log.warning("Failed to load holidays; proceeding without holiday exclusions", exc_info=True)
        return set()


def _load_days_off(uow, technician_id, date_from, date_to) -> set:
    """Return day-off dates for the requested technician and window.

    On any error falls back to an empty set so availability never 500s
    due to a day-off read failure.
    """
    try:
        from fsm.scheduling.adapters.time_off_repository import SqlAlchemyTimeOffRepository

        repo = SqlAlchemyTimeOffRepository(uow._session)
        return repo.list_between(technician_id, date_from, date_to)
    except Exception:
        _log.warning(
            "Failed to load days-off for technician %s; proceeding without day-off exclusions",
            technician_id,
            exc_info=True,
        )
        return set()


def _resolve_calendar(request: Request, technician_id):
    """Resolve the technician's CalendarPort so availability can subtract their free/busy.

    Falls back to NullCalendarPort on any failure so availability never 500s
    because Google is down or the connection is absent.
    """
    try:
        from fsm.platform.config import get_settings

        settings = getattr(request.app.state, "settings", None) or get_settings()
        session_factory = _get_session_factory(request)
        client_factory_override = getattr(
            request.app.state, "calendar_client_factory_override", None
        )
        kwargs = {}
        if client_factory_override is not None:
            kwargs["client_factory"] = client_factory_override
        resolver = build_calendar_resolver(session_factory, settings, **kwargs)
        return resolver(technician_id)
    except Exception:
        _log.warning(
            "Failed to resolve calendar for technician %s; proceeding without free/busy",
            technician_id,
            exc_info=True,
        )
        return NullCalendarPort()


def _get_settings(request: Request):
    """Return the Settings instance attached to the app state, or the process singleton."""
    from fsm.platform.config import get_settings

    return getattr(request.app.state, "settings", None) or get_settings()


# Key: scheduling domain error type. Value: the HTTP status every endpoint maps it to.
_DOMAIN_ERROR_STATUS: dict[type[SchedulingError], int] = {
    SlotUnavailable: 409,
    InvalidTransition: 409,
    NotFoundError: 404,
    InvalidTimeRange: 400,
    IncompleteContactInfo: 422,
}


def handle_scheduling_error(request: Request, exc: SchedulingError) -> JSONResponse:
    """App-level exception handler mapping scheduling domain errors to HTTP responses.

    Registered by create_app for the SchedulingError base, so every endpoint gets the
    same mapping without per-endpoint catch lists. A subclass with no entry in
    _DOMAIN_ERROR_STATUS re-raises rather than being absorbed with a guessed status.
    """
    for error_type, status_code in _DOMAIN_ERROR_STATUS.items():
        if isinstance(exc, error_type):
            return JSONResponse(status_code=status_code, content={"detail": str(exc)})
    raise exc


def _appointment_service(uow, request: Request) -> AppointmentService:
    """Build the AppointmentService shared by book/reschedule/cancel/add_details.

    The calendar port is a no-op stand-in: the mutation use cases never read it (only the
    availability query fetches busy time), and outbound calendar writes are enqueued to the
    outbox, whose dispatcher holds the real client. The contact resolver is consulted only by
    booking's contact-completeness guard; the other endpoints ignore it, and wiring it
    unconditionally keeps the factory uniform.
    """
    return AppointmentService(
        appointments=uow.appointments,
        service_calls=uow.service_calls,
        calendar=NullCalendarPort(),
        notifications=build_notifications(uow.session, _get_settings(request)),
        outbox=uow.outbox,
        contact_resolver=build_contact_resolver(uow.session),
    )


def _assert_self(technician_id: UUID, user: SessionUser) -> None:
    """Authorize a technician acting only on their own resources."""
    if technician_id != user.id:
        raise HTTPException(status_code=403, detail="Cannot act on behalf of another technician")


def _assert_participant(appt, user: SessionUser) -> None:
    """Authorize only the appointment's own customer or technician."""
    if user.id not in (appt.customer_id, appt.technician_id):
        raise HTTPException(status_code=403, detail="Not a participant of this appointment")


# ---------------------------------------------------------------------------
# Service calls
# ---------------------------------------------------------------------------


@router.post("/service-calls", response_model=ServiceCallResponse, status_code=201)
def open_service_call(
    body: OpenServiceCallRequest,
    request: Request,
    user: SessionUser = Depends(require_role(Role.CUSTOMER)),
) -> ServiceCallResponse:
    """Create a new OPEN service call for the authenticated customer and return it."""
    with _build_uow(request) as uow:
        svc = ServiceCallService(service_calls=uow.service_calls)
        sc = svc.open_service_call(
            customer_id=user.id,
            description=body.description,
        )
        uow.commit()

    return ServiceCallResponse(
        id=sc.id,
        customer_id=sc.customer_id,
        description=sc.description,
        status=sc.status.value,
        created_at=sc.created_at,
    )


# ---------------------------------------------------------------------------
# Availability
# ---------------------------------------------------------------------------


def _now_utc() -> datetime:
    """Current UTC instant used to exclude availability slots that begin in the past.

    Isolated as a module-level function so tests asserting availability for fixed
    historical dates can freeze it and observe deterministic slot sets.
    """
    return datetime.now(timezone.utc)


def _compute_slots(
    request: Request,
    uow,
    technician_id: UUID,
    date_from: date,
    date_to: date,
    slot_minutes: int,
    tz_hint: zoneinfo.ZoneInfo | None = None,
) -> list[TimeRange]:
    """Return proposed availability slots for one technician over a date range.

    Applies working hours, the technician's stored timezone (falling back to tz_hint
    or the region default), holiday exclusions, day-off exclusions, and free/busy
    subtraction from the technician's connected calendar. Holiday, day-off, and
    calendar reads fail open on any error, mirroring the individual helper functions.
    An unresolvable stored timezone falls back to tz_hint; stored hours that fail
    domain validation fall back to the standard Israeli work-week schedule. Any
    other error propagates rather than being silently absorbed.
    """
    from fsm.scheduling.adapters.working_hours_repository import (
        SqlAlchemyWorkingHoursRepository,
    )

    tz_info: zoneinfo.ZoneInfo = tz_hint if tz_hint is not None else zoneinfo.ZoneInfo(DEFAULT_TIMEZONE)
    wh_repo = SqlAlchemyWorkingHoursRepository(uow._session)

    stored_tz = wh_repo.get_timezone(technician_id)
    if stored_tz is not None:
        try:
            tz_info = zoneinfo.ZoneInfo(stored_tz)
        except zoneinfo.ZoneInfoNotFoundError:
            _log.warning(
                "Unknown stored timezone %r for technician %s; falling back to caller-supplied timezone",
                stored_tz,
                technician_id,
            )

    try:
        working_hours = wh_repo.get_for_technician(technician_id)
    except SchedulingError:
        _log.warning(
            "Corrupt stored working hours for technician %s; falling back to default schedule",
            technician_id,
            exc_info=True,
        )
        working_hours = WeeklyWorkingHours.default()

    holidays = _load_holidays(request, uow, date_from, date_to)
    days_off = _load_days_off(uow, technician_id, date_from, date_to)
    excluded_dates = holidays | days_off

    calendar = _resolve_calendar(request, technician_id)
    svc = AppointmentService(
        appointments=uow.appointments,
        service_calls=uow.service_calls,
        calendar=calendar,
        notifications=LoggingNotificationPort(),
        outbox=uow.outbox,
        clock=_now_utc,
    )
    return svc.propose_slots(
        technician_id=technician_id,
        working_hours=working_hours,
        tz=tz_info,
        start_date=date_from,
        end_date=date_to,
        slot_duration=timedelta(minutes=slot_minutes),
        holidays=excluded_dates,
    )


@router.get("/availability", response_model=AvailabilityResponse)
def get_availability(
    request: Request,
    technician_id: Annotated[UUID, Query()],
    date_from: Annotated[date, Query()],
    date_to: Annotated[date, Query()],
    slot_minutes: Annotated[int, Query(ge=1)] = 60,
    tz: Annotated[str, Query()] = DEFAULT_TIMEZONE,
) -> AvailabilityResponse:
    """Return available booking slots for a technician over a date range."""
    try:
        tz_info = zoneinfo.ZoneInfo(tz)
    except zoneinfo.ZoneInfoNotFoundError:
        raise HTTPException(status_code=400, detail=f"Unknown timezone: {tz!r}")

    with _build_uow(request) as uow:
        slots = _compute_slots(request, uow, technician_id, date_from, date_to, slot_minutes, tz_info)

    return AvailabilityResponse(
        slots=[SlotResponse(start=s.start, end=s.end) for s in slots]
    )


@router.get("/availability/pool", response_model=PooledAvailabilityResponse)
def get_availability_pool(
    request: Request,
    date_from: Annotated[date, Query()],
    date_to: Annotated[date, Query()],
    slot_minutes: Annotated[int, Query(ge=1)] = 60,
    limit: Annotated[int | None, Query(ge=1)] = None,
) -> PooledAvailabilityResponse:
    """Return pooled availability slots across connected approved technicians (first-available).

    Single pool with no skills routing. The candidate pool is the set of APPROVED technicians
    who have completed calendar onboarding (status=CONNECTED); a connected calendar alone is not
    enough — a user whose technician role is pending or rejected is never offered, so the admin
    approval queue cannot be bypassed. Each slot is tagged with its technician_id and display
    name so the customer's choice implicitly selects the earliest-available technician. Results
    are sorted by start then technician_id; limit caps them to the earliest N when given.
    """
    from fsm.calendar.adapters.repositories import SqlAlchemyCalendarConnectionRepository
    from fsm.identity.adapters.repositories import SqlAlchemyUserRepository

    ranked: list[tuple[UUID, datetime, datetime]] = []
    # Key: technician id. Value: the name every pooled slot, notification, and calendar event renders.
    names: dict[UUID, str] = {}

    with _build_uow(request) as uow:
        connections = SqlAlchemyCalendarConnectionRepository(uow._session).list_connected()
        users = SqlAlchemyUserRepository(uow._session)

        for conn in connections:
            # A connection is only ever created for a signed-in user whose id is this
            # technician_id, so the identity row is guaranteed present.
            user = users.get(conn.technician_id)
            if not user.is_approved_technician:
                continue
            names[conn.technician_id] = user.preferred_name

            try:
                slots = _compute_slots(
                    request, uow, conn.technician_id, date_from, date_to, slot_minutes
                )
            except Exception:
                _log.warning(
                    "Failed to compute slots for technician %s; skipping from pool",
                    conn.technician_id,
                    exc_info=True,
                )
                continue

            for slot in slots:
                ranked.append((conn.technician_id, slot.start, slot.end))

        ranked.sort(key=lambda r: (r[1], str(r[0])))
        if limit is not None:
            ranked = ranked[:limit]

    return PooledAvailabilityResponse(
        slots=[
            PooledSlotResponse(
                technician_id=tech_id,
                technician_name=names[tech_id],
                start=start,
                end=end,
            )
            for tech_id, start, end in ranked
        ]
    )


# ---------------------------------------------------------------------------
# Days off
# ---------------------------------------------------------------------------


@router.post("/technicians/{technician_id}/days-off", status_code=201)
def add_day_off(
    technician_id: UUID,
    body: DayOffRequest,
    request: Request,
    user: SessionUser = Depends(require_role(Role.TECHNICIAN)),
) -> None:
    """Mark a date as a day off for a technician; idempotent."""
    from fsm.scheduling.adapters.time_off_repository import SqlAlchemyTimeOffRepository

    _assert_self(technician_id, user)
    with _build_uow(request) as uow:
        repo = SqlAlchemyTimeOffRepository(uow._session)
        repo.add(technician_id, body.date)
        uow.commit()


@router.delete("/technicians/{technician_id}/days-off/{off_date}", status_code=204)
def remove_day_off(
    technician_id: UUID,
    off_date: date,
    request: Request,
    user: SessionUser = Depends(require_role(Role.TECHNICIAN)),
) -> None:
    """Remove a previously marked day off; no-op if absent."""
    from fsm.scheduling.adapters.time_off_repository import SqlAlchemyTimeOffRepository

    _assert_self(technician_id, user)
    with _build_uow(request) as uow:
        repo = SqlAlchemyTimeOffRepository(uow._session)
        repo.remove(technician_id, off_date)
        uow.commit()


@router.get("/technicians/{technician_id}/days-off", response_model=DaysOffResponse)
def list_days_off(
    technician_id: UUID,
    request: Request,
    date_from: Annotated[date, Query()],
    date_to: Annotated[date, Query()],
    user: SessionUser = Depends(require_role(Role.TECHNICIAN)),
) -> DaysOffResponse:
    """List day-off dates for a technician within a date range."""
    from fsm.scheduling.adapters.time_off_repository import SqlAlchemyTimeOffRepository

    _assert_self(technician_id, user)
    with _build_uow(request) as uow:
        repo = SqlAlchemyTimeOffRepository(uow._session)
        days = sorted(repo.list_between(technician_id, date_from, date_to))
    return DaysOffResponse(days_off=days)


# ---------------------------------------------------------------------------
# Working hours
# ---------------------------------------------------------------------------


@router.put("/technicians/{technician_id}/working-hours", response_model=WorkingHoursResponse)
def put_working_hours(
    technician_id: UUID,
    body: WorkingHoursRequest,
    request: Request,
    user: SessionUser = Depends(require_role(Role.TECHNICIAN)),
) -> WorkingHoursResponse:
    """Store the technician's weekly working-hours schedule, replacing any existing configuration."""
    from fsm.scheduling.adapters.working_hours_repository import SqlAlchemyWorkingHoursRepository

    _assert_self(technician_id, user)
    # Any construction failure here is a malformed request body, so every SchedulingError maps
    # to 400 — including bare SchedulingError (duplicate weekday), which the app-level handler
    # deliberately does not map.
    try:
        windows = tuple(
            DailyHours(weekday=w.weekday, start=w.start, end=w.end) for w in body.windows
        )
        hours = WeeklyWorkingHours(windows=windows)
    except SchedulingError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    with _build_uow(request) as uow:
        repo = SqlAlchemyWorkingHoursRepository(uow._session)
        repo.set_for_technician(technician_id, hours)
        uow.commit()

    return WorkingHoursResponse(
        windows=[DailyHoursSchema(weekday=dh.weekday, start=dh.start, end=dh.end) for dh in hours.windows]
    )


@router.get("/technicians/{technician_id}/working-hours", response_model=WorkingHoursResponse)
def get_working_hours(
    technician_id: UUID,
    request: Request,
    user: SessionUser = Depends(require_role(Role.TECHNICIAN)),
) -> WorkingHoursResponse:
    """Return the technician's working-hours schedule (default when unset)."""
    from fsm.scheduling.adapters.working_hours_repository import SqlAlchemyWorkingHoursRepository

    _assert_self(technician_id, user)
    with _build_uow(request) as uow:
        repo = SqlAlchemyWorkingHoursRepository(uow._session)
        hours = repo.get_for_technician(technician_id)

    return WorkingHoursResponse(
        windows=[DailyHoursSchema(weekday=dh.weekday, start=dh.start, end=dh.end) for dh in hours.windows]
    )


@router.put("/technicians/{technician_id}/timezone", response_model=TimezoneResponse)
def put_timezone(
    technician_id: UUID,
    body: TimezoneRequest,
    request: Request,
    user: SessionUser = Depends(require_role(Role.TECHNICIAN)),
) -> TimezoneResponse:
    """Store the technician's IANA timezone, validating it against the system timezone database."""
    from fsm.scheduling.adapters.working_hours_repository import SqlAlchemyWorkingHoursRepository

    _assert_self(technician_id, user)
    try:
        zoneinfo.ZoneInfo(body.timezone)
    except zoneinfo.ZoneInfoNotFoundError:
        raise HTTPException(status_code=400, detail=f"Unknown timezone: {body.timezone!r}")

    with _build_uow(request) as uow:
        repo = SqlAlchemyWorkingHoursRepository(uow._session)
        repo.set_timezone(technician_id, body.timezone)
        uow.commit()

    return TimezoneResponse(timezone=body.timezone)


@router.get("/technicians/{technician_id}/timezone", response_model=TimezoneResponse)
def get_timezone(
    technician_id: UUID,
    request: Request,
    user: SessionUser = Depends(require_role(Role.TECHNICIAN)),
) -> TimezoneResponse:
    """Return the technician's timezone (the region default when unset)."""
    from fsm.scheduling.adapters.working_hours_repository import SqlAlchemyWorkingHoursRepository

    _assert_self(technician_id, user)
    with _build_uow(request) as uow:
        repo = SqlAlchemyWorkingHoursRepository(uow._session)
        stored = repo.get_timezone(technician_id)

    return TimezoneResponse(timezone=stored if stored is not None else DEFAULT_TIMEZONE)


# ---------------------------------------------------------------------------
# Appointments
# ---------------------------------------------------------------------------


@router.post("/appointments", response_model=AppointmentResponse)
def book_appointment(
    body: BookAppointmentRequest,
    request: Request,
    user: SessionUser = Depends(require_role(Role.CUSTOMER)),
) -> AppointmentResponse:
    """Book a new appointment for the authenticated customer's OPEN service call."""
    time_range = TimeRange(start=body.start, end=body.end)

    from fsm.identity.adapters.repositories import SqlAlchemyUserRepository
    from fsm.identity.domain.errors import NotFoundError as UserNotFoundError

    with _build_uow(request) as uow:
        # The booking customer must own the service call they book against.
        service_call = uow.service_calls.get(body.service_call_id)
        if service_call.customer_id != user.id:
            raise HTTPException(
                status_code=403,
                detail="Cannot book against another customer's service call",
            )
        # Only an APPROVED technician is a bookable target; an unknown id and a user whose
        # technician role is pending or rejected are equally nonexistent to the booking
        # customer, so booking cannot bypass the admin approval queue.
        try:
            target_is_bookable = (
                SqlAlchemyUserRepository(uow.session).get(body.technician_id).is_approved_technician
            )
        except UserNotFoundError:
            target_is_bookable = False
        if not target_is_bookable:
            raise HTTPException(status_code=404, detail="Technician not found")
        appt = _appointment_service(uow, request).book_appointment(
            service_call_id=body.service_call_id,
            technician_id=body.technician_id,
            customer_id=user.id,
            time_range=time_range,
        )
        uow.commit()

    return _appt_response(appt)


@router.post("/appointments/{appointment_id}/reschedule", response_model=AppointmentResponse)
def reschedule_appointment(
    appointment_id: UUID,
    body: RescheduleRequest,
    request: Request,
    user: SessionUser = Depends(require_user),
) -> AppointmentResponse:
    """Reschedule an existing appointment to a new time window."""
    new_range = TimeRange(start=body.start, end=body.end)

    with _build_uow(request) as uow:
        _assert_participant(uow.appointments.get(appointment_id), user)
        appt = _appointment_service(uow, request).reschedule_appointment(
            appointment_id=appointment_id,
            new_time_range=new_range,
        )
        uow.commit()

    return _appt_response(appt)


@router.post("/appointments/{appointment_id}/cancel", response_model=AppointmentResponse)
def cancel_appointment(
    appointment_id: UUID,
    request: Request,
    user: SessionUser = Depends(require_user),
) -> AppointmentResponse:
    """Cancel an appointment."""
    with _build_uow(request) as uow:
        _assert_participant(uow.appointments.get(appointment_id), user)
        appt = _appointment_service(uow, request).cancel_appointment(appointment_id=appointment_id)
        uow.commit()

    return _appt_response(appt)


@router.post("/appointments/{appointment_id}/details", response_model=AppointmentResponse)
def add_details(
    appointment_id: UUID,
    body: AddDetailsRequest,
    request: Request,
    user: SessionUser = Depends(require_user),
) -> AppointmentResponse:
    """Attach or replace free-text details on an appointment."""
    with _build_uow(request) as uow:
        _assert_participant(uow.appointments.get(appointment_id), user)
        appt = _appointment_service(uow, request).add_details(appointment_id=appointment_id, text=body.text)
        uow.commit()

    return _appt_response(appt)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _appt_response(appt) -> AppointmentResponse:
    return AppointmentResponse(
        id=appt.id,
        service_call_id=appt.service_call_id,
        technician_id=appt.technician_id,
        customer_id=appt.customer_id,
        start=appt.time_range.start,
        end=appt.time_range.end,
        status=appt.status.value,
        details=appt.details,
        external_event_id=appt.external_event_id,
        created_at=appt.created_at,
        updated_at=appt.updated_at,
    )
