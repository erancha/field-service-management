"""SQLAlchemy ORM row classes for the scheduling bounded context.

These are infrastructure-layer data containers only. Domain entities remain pure
dataclasses; the repositories map between these rows and domain objects.
"""
from __future__ import annotations

from datetime import date, time

from sqlalchemy import Date, Index, Integer, PrimaryKeyConstraint, SmallInteger, String, Text, Time
from sqlalchemy.dialects.postgresql import TIMESTAMP, UUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from fsm.shared.db import Base


class ServiceCallRow(Base):
    """Persistent row for a service call."""

    __tablename__ = "service_call"

    id: Mapped[UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    customer_id: Mapped[UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    description: Mapped[str] = mapped_column(String, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[TIMESTAMP] = mapped_column(TIMESTAMP(timezone=True), nullable=False)


class AppointmentRow(Base):
    """Persistent row for an appointment, storing the time interval as start_at / end_at.

    The GiST exclusion constraint (added in the Alembic migration) enforces that no two
    non-cancelled appointments for the same technician can occupy an overlapping
    half-open [start_at, end_at) window.
    """

    __tablename__ = "appointment"

    id: Mapped[UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    service_call_id: Mapped[UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    technician_id: Mapped[UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    customer_id: Mapped[UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    start_at: Mapped[TIMESTAMP] = mapped_column(TIMESTAMP(timezone=True), nullable=False)
    end_at: Mapped[TIMESTAMP] = mapped_column(TIMESTAMP(timezone=True), nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False)
    details: Mapped[str | None] = mapped_column(String, nullable=True)
    external_event_id: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[TIMESTAMP] = mapped_column(TIMESTAMP(timezone=True), nullable=False)
    updated_at: Mapped[TIMESTAMP] = mapped_column(TIMESTAMP(timezone=True), nullable=False)


class OutboxRow(Base):
    """Persistent row for a pending calendar projection operation.

    status transitions: PENDING → PROCESSED (on success) or PENDING → FAILED (after mark_failed).
    attempts counts dispatcher runs that touched this row.
    external_event_id is stored for DELETE operations so the dispatcher can call delete_event
    even when the appointment's external_event_id may have been set after the enqueue.
    """

    __tablename__ = "calendar_outbox"

    id: Mapped[UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    operation: Mapped[str] = mapped_column(String, nullable=False)
    appointment_id: Mapped[UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    external_event_id: Mapped[str | None] = mapped_column(String, nullable=True)
    status: Mapped[str] = mapped_column(String, nullable=False, default="PENDING")
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[TIMESTAMP] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default=func.now()
    )
    processed_at: Mapped[TIMESTAMP | None] = mapped_column(TIMESTAMP(timezone=True), nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)


class AppointmentAuditRow(Base):
    """Append-only audit row recording a single appointment lifecycle transition.

    Rows are written by the repository in the same transaction as the appointment
    row, so the log is always consistent with entity state. appointment_id is indexed
    for efficient per-appointment history queries.
    """

    __tablename__ = "appointment_audit"
    __table_args__ = (
        Index("ix_appointment_audit_appointment_id", "appointment_id"),
    )

    id: Mapped[UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    appointment_id: Mapped[UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    action: Mapped[str] = mapped_column(String, nullable=False)
    occurred_at: Mapped[TIMESTAMP] = mapped_column(TIMESTAMP(timezone=True), nullable=False)


class HolidayRow(Base):
    """Persistent row for a cached public holiday.

    holiday_date is the primary key; upsert by date replaces the name.
    """

    __tablename__ = "holiday"

    holiday_date: Mapped[date] = mapped_column(Date, primary_key=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)


class TimeOffRow(Base):
    """Persistent row for a technician-marked day off.

    Composite primary key (technician_id, off_date) enforces one row per
    technician per date; the `add` adapter uses ON CONFLICT DO NOTHING for
    idempotent inserts.
    """

    __tablename__ = "time_off"
    __table_args__ = (PrimaryKeyConstraint("technician_id", "off_date"),)

    technician_id: Mapped[UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    off_date: Mapped[date] = mapped_column(Date, nullable=False)


class WorkingHoursRow(Base):
    """Persistent row for one weekday window in a technician's working-hours schedule.

    Composite PK (technician_id, weekday) enforces one window per day per technician.
    weekday follows Python's date.weekday() convention (Mon=0 … Sun=6).
    """

    __tablename__ = "working_hours"
    __table_args__ = (PrimaryKeyConstraint("technician_id", "weekday"),)

    technician_id: Mapped[UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    weekday: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    start_time: Mapped[time] = mapped_column(Time, nullable=False)
    end_time: Mapped[time] = mapped_column(Time, nullable=False)


class TechnicianTimezoneRow(Base):
    """Persistent row for a technician's IANA timezone preference.

    technician_id is the sole PK; upsert via ON CONFLICT DO UPDATE replaces the value.
    """

    __tablename__ = "technician_timezone"

    technician_id: Mapped[UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    timezone: Mapped[str] = mapped_column(Text, nullable=False)
