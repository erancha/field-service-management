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
- BookingRateLimited                  → 429 Too Many Requests
"""
from __future__ import annotations

import logging
import zoneinfo
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Annotated, Literal
from urllib.parse import quote
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from fastapi.responses import JSONResponse

from fsm.assist.ports.chat_model import TriageSummary
from fsm.assist.ports.photo_store import original_key, preview_key
from fsm.scheduling.application.appointment_service import AppointmentService
from fsm.scheduling.application.service_call_service import ServiceCallService
from fsm.scheduling.domain.booking_rate_limit import CancellationRateLimit
from fsm.scheduling.domain.errors import (
    BookingRateLimited,
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
    ServiceCallPhotoResponse,
    ServiceCallResponse,
    SlotResponse,
    SummaryBlockResponse,
    UpcomingAppointmentResponse,
    UpcomingAppointmentsResponse,
    WorkingHoursRequest,
    WorkingHoursResponse,
)
from fsm.platform.calendar_resolver import build_calendar_resolver
from fsm.platform.dev_adapters import LoggingNotificationPort, NullCalendarPort
from fsm.platform.events import publish_appointment_changed
from fsm.platform.identity_lookup import build_contact_resolver
from fsm.platform.notifications_factory import build_notifications
from fsm.platform.api.auth_deps import SessionUser, require_role, require_user
from fsm.identity.domain.role import Role

_log = logging.getLogger(__name__)

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


def _load_holidays(request: Request, uow, date_from, date_to) -> set:
    """Return cached holiday dates for the requested window.

    On any error, falls back to an empty set so availability never 500s
    due to a holiday-read failure.
    """
    try:
        from fsm.scheduling.adapters.holiday_repository import SqlAlchemyHolidayRepository

        repo = SqlAlchemyHolidayRepository(uow.session)
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

        repo = SqlAlchemyTimeOffRepository(uow.session)
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
    BookingRateLimited: 429,
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


def _cancellation_limit(settings) -> CancellationRateLimit | None:
    """Build the booking churn limit from settings; a limit of 0 turns the check off."""
    if settings.fsm_booking_cancel_limit == 0:
        return None
    return CancellationRateLimit(
        max_cancellations=settings.fsm_booking_cancel_limit,
        window=timedelta(hours=settings.fsm_booking_cancel_window_hours),
        cooloff=timedelta(hours=settings.fsm_booking_cancel_cooloff_hours),
    )


def _appointment_service(uow, request: Request) -> AppointmentService:
    """Build the AppointmentService shared by book/reschedule/cancel/add_details.

    The calendar port is a no-op stand-in: the mutation use cases never read it (only the
    availability query fetches busy time), and outbound calendar writes are enqueued to the
    outbox, whose dispatcher holds the real client. The contact resolver and cancellation
    limit are consulted only by booking's guards; the other endpoints ignore them, and
    wiring them unconditionally keeps the factory uniform.
    """
    settings = _get_settings(request)
    return AppointmentService(
        appointments=uow.appointments,
        service_calls=uow.service_calls,
        calendar=NullCalendarPort(),
        notifications=build_notifications(uow.session, settings),
        outbox=uow.outbox,
        contact_resolver=build_contact_resolver(uow.session),
        cancellation_limit=_cancellation_limit(settings),
        display_tz=zoneinfo.ZoneInfo(settings.timezone),
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
# Service-call photos
# ---------------------------------------------------------------------------


def _photo_store(request: Request):
    """Return the app's photo object store, or fail with 503 when the feature is disabled."""
    store = getattr(request.app.state, "photo_store", None)
    if store is None:
        raise HTTPException(status_code=503, detail="Photo storage not configured")
    return store


def _content_disposition(disposition: str, filename: str) -> str:
    """Build a Content-Disposition value from a customer-controlled filename.

    Response headers are Latin-1 encoded by Starlette, so a filename with non-ASCII
    characters (Hebrew, CJK, emoji, ...) must never be interpolated as-is: doing so raises
    UnicodeEncodeError and turns the download into an unhandled 500. Per RFC 6266/5987, this
    emits both a plain-ASCII fallback filename for clients that only understand the legacy
    form, and a percent-encoded filename* for clients that render the real name.
    """
    # Backslashes are stripped with the quotes and newlines: inside the quoted fallback a
    # backslash escapes the character after it, so a trailing one would swallow the closing quote.
    safe_name = (
        filename.replace('"', "").replace("\\", "").replace("\r", "").replace("\n", "")
    )
    # A name with no ASCII at all cannot have an ASCII extension either, so the fallback is fixed.
    ascii_name = safe_name.encode("ascii", errors="ignore").decode("ascii").strip() or "photo"
    # RFC 5987's attr-char grammar admits no bare "/", which quote() would keep by default.
    encoded_name = quote(safe_name, safe="")
    return f'{disposition}; filename="{ascii_name}"; filename*=UTF-8\'\'{encoded_name}'


def _assert_call_participant(uow, call, user: SessionUser) -> None:
    """Authorize the call's customer, a technician appointed to it, or an administrator."""
    if user.role is Role.ADMIN or user.id == call.customer_id:
        return
    if any(
        appt.technician_id == user.id
        for appt in uow.appointments.list_for_service_call(call.id)
    ):
        return
    raise HTTPException(status_code=403, detail="Not a participant of this service call")


@router.get("/service-calls/{service_call_id}/photos/{photo_id}")
def download_service_call_photo(
    service_call_id: UUID,
    photo_id: UUID,
    request: Request,
    variant: Literal["original", "preview"] = "original",
    user: SessionUser = Depends(require_user),
) -> Response:
    """Serve one photo from the call, streaming the stored object through the session check."""
    with _build_uow(request) as uow:
        call = uow.service_calls.get(service_call_id)
        _assert_call_participant(uow, call, user)
        attachment = uow.attachments.get(photo_id)
        if attachment.service_call_id != service_call_id:
            raise HTTPException(status_code=404, detail="No such photo on this service call")

    # Both variants are served inline: the links in calendar events and the web app's thumbnail
    # clicks must display the image in the browser, and the header's filename still names a
    # save-as for anyone downloading.
    if variant == "original":
        key, media_type, disposition = (
            original_key(attachment.object_key), attachment.media_type, "inline"
        )
    else:
        key, media_type, disposition = (
            preview_key(attachment.object_key), "image/jpeg", "inline"
        )
    return Response(
        content=_photo_store(request).get(key),
        media_type=media_type,
        headers={"Content-Disposition": _content_disposition(disposition, attachment.filename)},
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
) -> list[TimeRange]:
    """Return proposed availability slots for one technician over a date range.

    Applies working hours, the service-region timezone, holiday exclusions, day-off
    exclusions, and free/busy subtraction from the technician's connected calendar.
    Holiday, day-off, and calendar reads fail open on any error, mirroring the individual
    helper functions. Stored hours that fail domain validation fall back to the standard
    Israeli work-week schedule. Any other error propagates rather than being silently absorbed.
    """
    from fsm.scheduling.adapters.working_hours_repository import (
        SqlAlchemyWorkingHoursRepository,
    )

    tz_info = zoneinfo.ZoneInfo(_get_settings(request).timezone)
    wh_repo = SqlAlchemyWorkingHoursRepository(uow.session)

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
) -> AvailabilityResponse:
    """Return available booking slots for a technician over a date range."""
    with _build_uow(request) as uow:
        slots = _compute_slots(request, uow, technician_id, date_from, date_to, slot_minutes)

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
    from fsm.google_calendar.adapters.repositories import SqlAlchemyCalendarConnectionRepository
    from fsm.identity.adapters.repositories import SqlAlchemyUserRepository

    ranked: list[tuple[UUID, datetime, datetime]] = []
    # Key: technician id. Value: the name every pooled slot, notification, and calendar event renders.
    names: dict[UUID, str] = {}

    with _build_uow(request) as uow:
        connections = SqlAlchemyCalendarConnectionRepository(uow.session).list_connected()
        users = SqlAlchemyUserRepository(uow.session)

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
        repo = SqlAlchemyTimeOffRepository(uow.session)
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
        repo = SqlAlchemyTimeOffRepository(uow.session)
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
        repo = SqlAlchemyTimeOffRepository(uow.session)
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
        repo = SqlAlchemyWorkingHoursRepository(uow.session)
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
        repo = SqlAlchemyWorkingHoursRepository(uow.session)
        hours = repo.get_for_technician(technician_id)

    return WorkingHoursResponse(
        windows=[DailyHoursSchema(weekday=dh.weekday, start=dh.start, end=dh.end) for dh in hours.windows]
    )


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

    _publish_appointment_changed(request.app, appt)
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

    _publish_appointment_changed(request.app, appt)
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

    _publish_appointment_changed(request.app, appt)
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

    _publish_appointment_changed(request.app, appt)
    return _appt_response(appt)


@router.get("/appointments/upcoming", response_model=UpcomingAppointmentsResponse)
def list_upcoming_appointments(
    request: Request,
    limit: Annotated[int, Query(ge=1)],
    user: SessionUser = Depends(require_user),
) -> UpcomingAppointmentsResponse:
    """Return the caller's soonest upcoming appointments, enriched for one-shot rendering.

    Scope follows the session role: a technician sees their own, a customer sees their own, an
    administrator sees all. Each item carries the problem text and both party names plus the
    customer address, resolved once per distinct id, so the client renders a row without any
    follow-up request.
    """
    from fsm.identity.adapters.repositories import SqlAlchemyUserRepository

    now = _now_utc()
    with _build_uow(request) as uow:
        if user.role is Role.TECHNICIAN:
            appts = uow.appointments.list_upcoming_for_technician(user.id, now, limit)
        elif user.role is Role.ADMIN:
            appts = uow.appointments.list_upcoming_all(now, limit)
        else:
            appts = uow.appointments.list_upcoming_for_customer(user.id, now, limit)

        users = SqlAlchemyUserRepository(uow.session)
        # Key: user id. Value: (preferred display name, address) resolved once per distinct id.
        user_cache: dict[UUID, tuple[str, str | None]] = {}
        # Key: service-call id. Value: what the row and card show of the problem — the description
        # text, the one-line headline, and the summary layout when triage wrote one.
        problem_cache: dict[UUID, _ProblemView] = {}
        # Key: service-call id. Value: its photo attachments, resolved once per distinct id.
        photo_cache: dict[UUID, list[ServiceCallPhotoResponse]] = {}

        def resolve_user(user_id: UUID) -> tuple[str, str | None]:
            if user_id not in user_cache:
                u = users.get(user_id)
                user_cache[user_id] = (u.preferred_name, u.address)
            return user_cache[user_id]

        def resolve_problem(service_call_id: UUID) -> _ProblemView:
            if service_call_id not in problem_cache:
                problem_cache[service_call_id] = _problem_view(
                    uow.service_calls.get(service_call_id)
                )
            return problem_cache[service_call_id]

        def resolve_photos(service_call_id: UUID) -> list[ServiceCallPhotoResponse]:
            if service_call_id not in photo_cache:
                photo_cache[service_call_id] = [
                    ServiceCallPhotoResponse(
                        id=a.id, filename=a.filename, size_bytes=a.size_bytes
                    )
                    for a in uow.attachments.list_for_service_call(service_call_id)
                ]
            return photo_cache[service_call_id]

        items = [
            UpcomingAppointmentResponse(
                id=appt.id,
                service_call_id=appt.service_call_id,
                technician_id=appt.technician_id,
                customer_id=appt.customer_id,
                start=appt.time_range.start,
                end=appt.time_range.end,
                status=appt.status.value,
                details=appt.details,
                problem=resolve_problem(appt.service_call_id).problem,
                headline=resolve_problem(appt.service_call_id).headline,
                summary=resolve_problem(appt.service_call_id).summary,
                technician_name=resolve_user(appt.technician_id)[0],
                customer_name=resolve_user(appt.customer_id)[0],
                address=resolve_user(appt.customer_id)[1],
                photos=resolve_photos(appt.service_call_id),
                created_at=appt.created_at,
            )
            for appt in appts
        ]

    return UpcomingAppointmentsResponse(items=items)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _ProblemView:
    """What one service call contributes to an appointment row: text, headline, and layout."""

    problem: str
    headline: str
    summary: list[SummaryBlockResponse] | None


def _problem_view(service_call) -> _ProblemView:
    """Project a service call's problem for the API.

    A call the triage assistant escalated carries the summary as structure, so the response ships
    the same layout the calendar renders and the client renders it rather than reading the text
    back apart. A call opened from the plain description form has only its description, whose first
    line stands in as the headline.
    """
    if service_call.triage_summary is None:
        return _ProblemView(
            problem=service_call.description,
            headline=service_call.description.split("\n", 1)[0],
            summary=None,
        )
    summary = TriageSummary.from_dict(service_call.triage_summary)
    return _ProblemView(
        problem=service_call.description,
        headline=summary.headline(),
        summary=[
            SummaryBlockResponse(
                heading=block.heading,
                bullets=list(block.bullets),
                fields=[(label, value) for label, value in block.fields],
            )
            for block in summary.blocks()
        ],
    )


def _publish_appointment_changed(app, appt) -> None:
    """Fire the live-refresh cue for both participants and the back office after a mutation."""
    publish_appointment_changed(
        app,
        appointment_id=appt.id,
        customer_id=appt.customer_id,
        technician_id=appt.technician_id,
    )


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
