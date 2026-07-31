"""Service layer for appointment lifecycle management.

Booking use cases enqueue a calendar operation in the same transaction as the
DB writes. A separate CalendarProjectionDispatcher reads the outbox and projects
those operations to the external calendar system asynchronously, so a calendar
outage can neither fail nor reorder a booking and no projection is lost on a crash.
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timedelta, timezone, tzinfo
from typing import Callable, Container
from uuid import UUID, uuid4

from fsm.scheduling.domain.appointment import Appointment, AppointmentStatus
from fsm.scheduling.domain.availability import generate_slots
from fsm.scheduling.domain.booking_rate_limit import CancellationRateLimit
from fsm.scheduling.domain.contact_info import ContactInfo
from fsm.scheduling.domain.errors import (
    BookingRateLimited,
    IncompleteContactInfo,
    InvalidTransition,
    SlotUnavailable,
)
from fsm.scheduling.domain.service_call import ServiceCallStatus
from fsm.scheduling.domain.time_range import TimeRange
from fsm.scheduling.domain.working_hours import WeeklyWorkingHours
from fsm.scheduling.ports.calendar import CalendarPort
from fsm.scheduling.ports.notifications import NotificationPort
from fsm.scheduling.ports.outbox import OutboxOperation, OutboxRepository
from fsm.scheduling.ports.repositories import AppointmentRepository, ServiceCallRepository

_log = logging.getLogger(__name__)


class AppointmentService:
    """Orchestrates appointment booking, rescheduling, cancellation, and slot proposals.

    Core responsibilities:
    - Validates service call state before any mutation
    - Computes free slots by merging calendar-busy ranges with existing appointments
    - Enforces no-overlap constraint before booking or rescheduling
    - Persists mutations and enqueues outbox entries in the same transaction
    - Rejects a booking whose customer or technician lacks required contact data
    - Pauses booking for a customer whose recent cancellations exceed the churn limit
    - Delegates external calendar projection to CalendarProjectionDispatcher via the outbox

    contact_resolver maps a user id to their ContactInfo, injected so the layer stays identity-free.
    It is consulted only by book_appointment; when unset, booking treats all contact as absent and
    rejects (fail closed), so a booking path that forgets to wire it cannot silently skip the check.

    cancellation_limit caps a customer's book/cancel churn, counted from the audit log's
    CANCELLED records. None disables the limit; like contact_resolver it is consulted only
    by book_appointment. display_tz is the zone the rejection renders its reopen time in —
    it affects only that message, never stored timestamps.
    """

    def __init__(
        self,
        appointments: AppointmentRepository,
        service_calls: ServiceCallRepository,
        calendar: CalendarPort,
        notifications: NotificationPort,
        outbox: OutboxRepository,
        clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
        new_id: Callable[[], UUID] = uuid4,
        contact_resolver: Callable[[UUID], ContactInfo] | None = None,
        cancellation_limit: CancellationRateLimit | None = None,
        display_tz: tzinfo = timezone.utc,
    ) -> None:
        self._appointments = appointments
        self._service_calls = service_calls
        self._calendar = calendar
        self._notifications = notifications
        self._outbox = outbox
        self._clock = clock
        self._new_id = new_id
        self._contact_resolver = contact_resolver
        self._cancellation_limit = cancellation_limit
        self._display_tz = display_tz

    def propose_slots(
        self,
        technician_id: UUID,
        working_hours: WeeklyWorkingHours,
        tz: tzinfo,
        start_date: date,
        end_date: date,
        slot_duration: timedelta,
        holidays: Container[date] = (),
    ) -> list[TimeRange]:
        """Return free slots for a technician across [start_date, end_date].

        Busy time is the union of calendar-reported blocks and time ranges
        occupied by the technician's existing active appointments.

        The query window is [start_date 00:00, end_date+1 00:00) (half-open), consistent
        with the repository's half-open overlap contract.

        Slots whose start is before the current time are excluded, so a past time is
        never offered even when start_date is today.
        """
        window_start = datetime(
            start_date.year, start_date.month, start_date.day, 0, 0, tzinfo=tz
        )
        next_day = end_date + timedelta(days=1)
        window_end = datetime(
            next_day.year, next_day.month, next_day.day, 0, 0, tzinfo=tz
        )
        calendar_busy = self._calendar.get_busy(technician_id, window_start, window_end)
        appt_busy = [
            a.time_range
            for a in self._appointments.list_for_technician_between(
                technician_id, window_start, window_end
            )
        ]
        slots = generate_slots(
            working_hours=working_hours,
            start_date=start_date,
            end_date=end_date,
            busy=calendar_busy + appt_busy,
            holidays=holidays,
            slot_duration=slot_duration,
            tz=tz,
        )
        now = self._clock()
        return [slot for slot in slots if slot.start >= now]

    def book_appointment(
        self,
        service_call_id: UUID,
        technician_id: UUID,
        customer_id: UUID,
        time_range: TimeRange,
    ) -> Appointment:
        """Book a new appointment for a service call.

        Validates that the service call exists and is OPEN before any mutation.
        Raises NotFoundError if the service call does not exist.
        Raises InvalidTransition if the service call is not OPEN.
        Raises BookingRateLimited if the customer's recent cancellations exceed the
        configured churn limit.
        Raises IncompleteContactInfo if the customer lacks an address or phone, or the assigned
        technician lacks a phone.
        Raises SlotUnavailable if time_range overlaps any active appointment for the technician.

        external_event_id is left None at booking time; the dispatcher sets it after
        processing the CREATE outbox entry.
        """
        sc = self._service_calls.get(service_call_id)
        if sc.status is not ServiceCallStatus.OPEN:
            raise InvalidTransition(
                f"Cannot book against service call {service_call_id!r} "
                f"with status {sc.status.value!r}; only OPEN calls may be booked."
            )

        now = self._clock()
        self._guard_not_rate_limited(customer_id, now)
        self._guard_contact_complete(customer_id, technician_id)
        self._guard_no_overlap(technician_id, time_range, exclude_id=None)

        appt = Appointment(
            id=self._new_id(),
            service_call_id=service_call_id,
            technician_id=technician_id,
            customer_id=customer_id,
            time_range=time_range,
            status=AppointmentStatus.SCHEDULED,
            details=None,
            created_at=now,
            updated_at=now,
        )
        sc.mark_scheduled()
        appt.record_booked(now)

        self._appointments.add(appt)
        self._service_calls.save(sc)
        self._outbox.enqueue(OutboxOperation.CREATE, appt.id)

        _log.info(
            "Appointment booked: appointment_id=%s technician_id=%s",
            appt.id,
            appt.technician_id,
        )
        self._notifications.appointment_booked(appt)
        return appt

    def reschedule_appointment(
        self,
        appointment_id: UUID,
        new_time_range: TimeRange,
    ) -> Appointment:
        """Reschedule an existing appointment to a new time window.

        Raises SlotUnavailable if new_time_range overlaps any other active
        appointment for the same technician (the appointment itself is excluded).
        """
        appt = self._appointments.get(appointment_id)
        self._guard_no_overlap(appt.technician_id, new_time_range, exclude_id=appointment_id)

        now = self._clock()
        appt.reschedule(new_time_range, now=now)
        self._appointments.save(appt)
        self._outbox.enqueue(OutboxOperation.UPDATE, appt.id)
        _log.info(
            "Appointment rescheduled: appointment_id=%s technician_id=%s",
            appt.id,
            appt.technician_id,
        )
        self._notifications.appointment_rescheduled(appt)
        return appt

    def cancel_appointment(self, appointment_id: UUID) -> Appointment:
        """Cancel an appointment and enqueue a DELETE outbox entry.

        The external_event_id (if any) is captured at enqueue time so the dispatcher
        can delete the calendar event even after the appointment status changes.
        """
        appt = self._appointments.get(appointment_id)
        now = self._clock()
        appt.cancel(now=now)
        self._appointments.save(appt)
        self._outbox.enqueue(
            OutboxOperation.DELETE,
            appt.id,
            external_event_id=appt.external_event_id,
        )
        _log.info(
            "Appointment cancelled: appointment_id=%s technician_id=%s",
            appt.id,
            appt.technician_id,
        )
        self._notifications.appointment_cancelled(appt)
        return appt

    def add_details(self, appointment_id: UUID, text: str) -> Appointment:
        """Attach free-text details to an appointment and propagate them to the calendar event.

        The outbox UPDATE re-projects the details into the shared FSM Google event; the customer,
        a guest on that event, is notified of the change by Google. The appointment_updated
        notification writes the in-app feed rows and emails the technician.
        """
        appt = self._appointments.get(appointment_id)
        now = self._clock()
        appt.add_details(text, now=now)
        self._appointments.save(appt)
        self._outbox.enqueue(OutboxOperation.UPDATE, appt.id)
        self._notifications.appointment_updated(appt)
        return appt

    def _guard_not_rate_limited(self, customer_id: UUID, now: datetime) -> None:
        """Reject the booking while the customer's recent cancellations exceed the churn limit."""
        if self._cancellation_limit is None:
            return
        cancellations = self._appointments.list_customer_cancellations_since(
            customer_id, now - self._cancellation_limit.window
        )
        retry_at = self._cancellation_limit.blocked_until(cancellations, now)
        if retry_at is not None:
            _log.warning(
                "BookingRateLimited: booking rejected; customer_id=%s cancellations=%d retry_at=%s",
                customer_id,
                len(cancellations),
                retry_at,
            )
            raise BookingRateLimited(retry_at.astimezone(self._display_tz))

    def _guard_contact_complete(self, customer_id: UUID, technician_id: UUID) -> None:
        """Reject the booking unless the customer has address+phone and the technician has a phone.

        With no resolver injected, every field reads as absent, so the booking fails closed.
        """
        customer = self._resolve_contact(customer_id)
        technician = self._resolve_contact(technician_id)
        missing: list[str] = []
        if not customer.has_address():
            missing.append("customer address")
        if not customer.has_phone():
            missing.append("customer phone")
        if not technician.has_phone():
            missing.append("technician phone")
        if missing:
            _log.warning(
                "IncompleteContactInfo: booking rejected; customer_id=%s technician_id=%s missing=%s",
                customer_id,
                technician_id,
                missing,
            )
            raise IncompleteContactInfo(missing)

    def _resolve_contact(self, user_id: UUID) -> ContactInfo:
        if self._contact_resolver is None:
            return ContactInfo()
        return self._contact_resolver(user_id)

    def _guard_no_overlap(
        self,
        technician_id: UUID,
        time_range: TimeRange,
        exclude_id: UUID | None,
    ) -> None:
        conflicting = self._appointments.list_for_technician_between(
            technician_id, time_range.start, time_range.end
        )
        for existing in conflicting:
            if existing.id == exclude_id:
                continue
            if existing.time_range.overlaps(time_range):
                _log.warning(
                    "SlotUnavailable: time_range=%s conflicts with appointment_id=%s "
                    "technician_id=%s",
                    time_range,
                    existing.id,
                    technician_id,
                )
                raise SlotUnavailable(
                    f"Time slot {time_range} conflicts with appointment {existing.id}"
                )
