"""SQLAlchemy repository adapters for the scheduling bounded context.

Each adapter wraps a SQLAlchemy Session and maps between ORM rows and
pure domain entities. The session's transaction lifecycle is controlled by the
caller; these adapters only flush, never commit.
"""
from __future__ import annotations

import logging
import uuid
from collections.abc import Sequence
from datetime import datetime

from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from fsm.scheduling.adapters.orm import (
    AppointmentAuditRow,
    AppointmentRow,
    ServiceCallAttachmentRow,
    ServiceCallRow,
)
from fsm.scheduling.domain.appointment import Appointment, AppointmentStatus, AuditAction
from fsm.scheduling.domain.attachment import ServiceCallAttachment
from fsm.scheduling.domain.errors import NotFoundError, SlotUnavailable
from fsm.scheduling.domain.service_call import ServiceCall, ServiceCallStatus
from fsm.scheduling.domain.time_range import TimeRange

_log = logging.getLogger(__name__)

_OVERLAP_CONSTRAINT = "appointment_no_overlap"


def _translate_integrity_error(exc: IntegrityError) -> None:
    """Re-raise exc as SlotUnavailable when it originates from the overlap constraint.

    Inspects the psycopg diagnostic constraint_name first; falls back to a
    substring check on the stringified original error for other drivers.
    For any other IntegrityError the original exception propagates unchanged.
    """
    constraint = getattr(getattr(exc.orig, "diag", None), "constraint_name", None)
    if constraint is None:
        constraint = _OVERLAP_CONSTRAINT if _OVERLAP_CONSTRAINT in str(exc.orig) else None
    if constraint == _OVERLAP_CONSTRAINT:
        _log.warning("Overlap constraint fired (%s); translating to SlotUnavailable", constraint)
        raise SlotUnavailable(
            "Appointment time slot conflicts with an existing active appointment "
            f"(constraint: {_OVERLAP_CONSTRAINT})"
        ) from exc
    raise exc


def _row_to_service_call(row: ServiceCallRow) -> ServiceCall:
    return ServiceCall(
        id=row.id,
        customer_id=row.customer_id,
        description=row.description,
        status=ServiceCallStatus(row.status),
        created_at=row.created_at,
        triage_summary=row.triage_summary,
        headline=row.headline,
    )


def _service_call_to_row(sc: ServiceCall) -> ServiceCallRow:
    return ServiceCallRow(
        id=sc.id,
        customer_id=sc.customer_id,
        description=sc.description,
        status=sc.status.value,
        created_at=sc.created_at,
        triage_summary=sc.triage_summary,
        headline=sc.headline,
    )


def _row_to_appointment(row: AppointmentRow) -> Appointment:
    return Appointment(
        id=row.id,
        service_call_id=row.service_call_id,
        technician_id=row.technician_id,
        customer_id=row.customer_id,
        time_range=TimeRange(start=row.start_at, end=row.end_at),
        status=AppointmentStatus(row.status),
        details=row.details,
        external_event_id=row.external_event_id,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _appointment_to_row(appt: Appointment) -> AppointmentRow:
    return AppointmentRow(
        id=appt.id,
        service_call_id=appt.service_call_id,
        technician_id=appt.technician_id,
        customer_id=appt.customer_id,
        start_at=appt.time_range.start,
        end_at=appt.time_range.end,
        status=appt.status.value,
        details=appt.details,
        external_event_id=appt.external_event_id,
        created_at=appt.created_at,
        updated_at=appt.updated_at,
    )


def _row_to_attachment(row: ServiceCallAttachmentRow) -> ServiceCallAttachment:
    return ServiceCallAttachment(
        id=row.id,
        service_call_id=row.service_call_id,
        filename=row.filename,
        media_type=row.media_type,
        size_bytes=row.size_bytes,
        object_key=row.object_key,
        created_at=row.created_at,
    )


class SqlAlchemyServiceCallRepository:
    """Session-scoped SQLAlchemy adapter for ServiceCall persistence."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def add(self, service_call: ServiceCall) -> None:
        """Insert a new service call row; caller ensures uniqueness of the id."""
        self._session.add(_service_call_to_row(service_call))
        self._session.flush()

    def get(self, service_call_id: uuid.UUID) -> ServiceCall:
        """Return the service call with the given id.

        Raises NotFoundError if absent.
        """
        row = self._session.get(ServiceCallRow, service_call_id)
        if row is None:
            raise NotFoundError(f"ServiceCall {service_call_id!r} not found")
        return _row_to_service_call(row)

    def save(self, service_call: ServiceCall) -> None:
        """Persist mutations to an already-stored service call."""
        row = self._session.get(ServiceCallRow, service_call.id)
        if row is None:
            raise NotFoundError(f"ServiceCall {service_call.id!r} not found")
        row.customer_id = service_call.customer_id
        row.description = service_call.description
        row.status = service_call.status.value
        row.created_at = service_call.created_at
        self._session.flush()

    def remove(self, service_call_id: uuid.UUID) -> None:
        """Delete the call row; attachment rows die with it via the FK cascade."""
        row = self._session.get(ServiceCallRow, service_call_id)
        if row is None:
            raise NotFoundError(f"ServiceCall {service_call_id!r} not found")
        self._session.delete(row)
        self._session.flush()


class SqlAlchemyAppointmentRepository:
    """Session-scoped SQLAlchemy adapter for Appointment persistence."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def add(self, appointment: Appointment) -> None:
        """Insert a new appointment row; caller ensures uniqueness of the id."""
        self._session.add(_appointment_to_row(appointment))
        try:
            self._session.flush()
        except IntegrityError as exc:
            _translate_integrity_error(exc)
        self._drain_audits(appointment)

    def get(self, appointment_id: uuid.UUID) -> Appointment:
        """Return the appointment with the given id.

        Raises NotFoundError if absent.
        """
        row = self._session.get(AppointmentRow, appointment_id)
        if row is None:
            raise NotFoundError(f"Appointment {appointment_id!r} not found")
        return _row_to_appointment(row)

    def save(self, appointment: Appointment) -> None:
        """Persist mutations to an already-stored appointment."""
        row = self._session.get(AppointmentRow, appointment.id)
        if row is None:
            raise NotFoundError(f"Appointment {appointment.id!r} not found")
        row.service_call_id = appointment.service_call_id
        row.technician_id = appointment.technician_id
        row.customer_id = appointment.customer_id
        row.start_at = appointment.time_range.start
        row.end_at = appointment.time_range.end
        row.status = appointment.status.value
        row.details = appointment.details
        row.external_event_id = appointment.external_event_id
        row.created_at = appointment.created_at
        row.updated_at = appointment.updated_at
        self._session.flush()
        self._drain_audits(appointment)

    def _drain_audits(self, appointment: Appointment) -> None:
        """Write one AppointmentAuditRow per pending audit record and flush.

        Called immediately after the appointment row flush succeeds, so audits
        are always written in the same transaction as the entity change.
        """
        records = appointment.drain_audits()
        if not records:
            return
        for record in records:
            self._session.add(
                AppointmentAuditRow(
                    id=uuid.uuid4(),
                    appointment_id=appointment.id,
                    action=record.action.value,
                    occurred_at=record.occurred_at,
                )
            )
        self._session.flush()

    def list_for_technician_between(
        self,
        technician_id: uuid.UUID,
        start: datetime,
        end: datetime,
    ) -> list[Appointment]:
        """Return active appointments for a technician overlapping [start, end).

        Uses a Postgres tstzrange overlap (&&) to enforce half-open boundary semantics:
        an appointment ending exactly at `start` or starting exactly at `end` is excluded.
        CANCELLED appointments are excluded regardless of their time range.
        """
        rows = (
            self._session.query(AppointmentRow)
            .filter(
                AppointmentRow.technician_id == technician_id,
                AppointmentRow.status != AppointmentStatus.CANCELLED.value,
                func.tstzrange(AppointmentRow.start_at, AppointmentRow.end_at, "[)").op("&&")(
                    func.tstzrange(start, end, "[)")
                ),
            )
            .all()
        )
        return [_row_to_appointment(row) for row in rows]

    def _list_upcoming(self, now: datetime, limit: int, *extra_filters) -> list[Appointment]:
        query = self._session.query(AppointmentRow).filter(
            AppointmentRow.status != AppointmentStatus.CANCELLED.value,
            AppointmentRow.end_at > now,
            *extra_filters,
        )
        rows = (
            query.order_by(AppointmentRow.start_at.asc(), AppointmentRow.id.asc())
            .limit(limit)
            .all()
        )
        return [_row_to_appointment(row) for row in rows]

    def list_upcoming_for_technician(
        self, technician_id: uuid.UUID, now: datetime, limit: int
    ) -> list[Appointment]:
        return self._list_upcoming(now, limit, AppointmentRow.technician_id == technician_id)

    def list_upcoming_for_customer(
        self, customer_id: uuid.UUID, now: datetime, limit: int
    ) -> list[Appointment]:
        return self._list_upcoming(now, limit, AppointmentRow.customer_id == customer_id)

    def list_upcoming_all(self, now: datetime, limit: int) -> list[Appointment]:
        return self._list_upcoming(now, limit)

    def list_for_service_call(self, service_call_id: uuid.UUID) -> list[Appointment]:
        rows = (
            self._session.query(AppointmentRow)
            .filter(AppointmentRow.service_call_id == service_call_id)
            .all()
        )
        return [_row_to_appointment(row) for row in rows]

    def list_customer_cancellations_since(
        self, customer_id: uuid.UUID, since: datetime
    ) -> list[datetime]:
        """Return occurred_at of each CANCELLED audit on this customer's appointments, >= since."""
        rows = (
            self._session.query(AppointmentAuditRow.occurred_at)
            .join(AppointmentRow, AppointmentRow.id == AppointmentAuditRow.appointment_id)
            .filter(
                AppointmentRow.customer_id == customer_id,
                AppointmentAuditRow.action == AuditAction.CANCELLED.value,
                AppointmentAuditRow.occurred_at >= since,
            )
            .all()
        )
        return [row.occurred_at for row in rows]


class SqlAlchemyServiceCallAttachmentRepository:
    """Session-scoped SQLAlchemy adapter for service-call photo attachments."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def add_all(self, attachments: Sequence[ServiceCallAttachment]) -> None:
        for attachment in attachments:
            self._session.add(
                ServiceCallAttachmentRow(
                    id=attachment.id,
                    service_call_id=attachment.service_call_id,
                    filename=attachment.filename,
                    media_type=attachment.media_type,
                    size_bytes=attachment.size_bytes,
                    object_key=attachment.object_key,
                    created_at=attachment.created_at,
                )
            )
        self._session.flush()

    def get(self, attachment_id: uuid.UUID) -> ServiceCallAttachment:
        row = self._session.get(ServiceCallAttachmentRow, attachment_id)
        if row is None:
            raise NotFoundError(f"Attachment {attachment_id!r} not found")
        return _row_to_attachment(row)

    def list_for_service_call(self, service_call_id: uuid.UUID) -> list[ServiceCallAttachment]:
        rows = (
            self._session.query(ServiceCallAttachmentRow)
            .filter(ServiceCallAttachmentRow.service_call_id == service_call_id)
            .order_by(ServiceCallAttachmentRow.created_at, ServiceCallAttachmentRow.id)
            .all()
        )
        return [_row_to_attachment(row) for row in rows]
