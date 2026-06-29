"""Pydantic request/response schemas for the scheduling API endpoints.

All datetime fields are timezone-aware ISO 8601 strings. UUIDs are validated
by Pydantic's UUID type and serialised as strings in responses.
"""
from __future__ import annotations

from datetime import date, datetime, time
from uuid import UUID

from pydantic import BaseModel, ConfigDict


# ---------------------------------------------------------------------------
# Service calls
# ---------------------------------------------------------------------------


class OpenServiceCallRequest(BaseModel):
    description: str


class ServiceCallResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    customer_id: UUID
    description: str
    status: str
    created_at: datetime


# ---------------------------------------------------------------------------
# Availability / slots
# ---------------------------------------------------------------------------


class SlotResponse(BaseModel):
    start: datetime
    end: datetime


class AvailabilityResponse(BaseModel):
    slots: list[SlotResponse]


class PooledSlotResponse(BaseModel):
    technician_id: UUID
    technician_name: str
    start: datetime
    end: datetime


class PooledAvailabilityResponse(BaseModel):
    slots: list[PooledSlotResponse]


# ---------------------------------------------------------------------------
# Appointments
# ---------------------------------------------------------------------------


class BookAppointmentRequest(BaseModel):
    service_call_id: UUID
    technician_id: UUID
    start: datetime
    end: datetime


class RescheduleRequest(BaseModel):
    start: datetime
    end: datetime


class AddDetailsRequest(BaseModel):
    text: str


class AppointmentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    service_call_id: UUID
    technician_id: UUID
    customer_id: UUID
    start: datetime
    end: datetime
    status: str
    details: str | None
    external_event_id: str | None
    created_at: datetime
    updated_at: datetime


# ---------------------------------------------------------------------------
# Days off
# ---------------------------------------------------------------------------


class DayOffRequest(BaseModel):
    date: date


class DaysOffResponse(BaseModel):
    days_off: list[date]


# ---------------------------------------------------------------------------
# Working hours
# ---------------------------------------------------------------------------


class DailyHoursSchema(BaseModel):
    weekday: int
    start: time
    end: time


class WorkingHoursRequest(BaseModel):
    windows: list[DailyHoursSchema]


class WorkingHoursResponse(BaseModel):
    windows: list[DailyHoursSchema]


# ---------------------------------------------------------------------------
# Timezone
# ---------------------------------------------------------------------------


class TimezoneRequest(BaseModel):
    timezone: str


class TimezoneResponse(BaseModel):
    timezone: str
