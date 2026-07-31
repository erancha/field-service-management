"""Pydantic request/response schemas for the scheduling API endpoints.

All datetime fields are timezone-aware ISO 8601 strings. UUIDs are validated
by Pydantic's UUID type and serialised as strings in responses.
"""
from __future__ import annotations

from datetime import date, datetime, time
from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StringConstraints


# ---------------------------------------------------------------------------
# Service calls
# ---------------------------------------------------------------------------


class OpenServiceCallRequest(BaseModel):
    # The problem description is required on every rendering surface (event title, notification
    # body), so a blank one is rejected at the door rather than surfacing as a placeholder later.
    description: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]


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


class ServiceCallPhotoResponse(BaseModel):
    id: UUID
    filename: str
    size_bytes: int


class SummaryBlockResponse(BaseModel):
    """A heading over either bullets or labelled fields; the other list is empty."""

    heading: str
    bullets: list[str]
    fields: list[tuple[str, str]]


class UpcomingAppointmentResponse(BaseModel):
    id: UUID
    service_call_id: UUID
    technician_id: UUID
    customer_id: UUID
    start: datetime
    end: datetime
    status: str
    details: str | None
    # problem is the service call's description as text; summary is the same content as the layout
    # every surface renders, present only for a call the triage assistant escalated. headline is
    # the fault in one line, for the row that has one line to show.
    problem: str
    headline: str
    summary: list[SummaryBlockResponse] | None
    technician_name: str
    customer_name: str
    address: str | None
    photos: list[ServiceCallPhotoResponse]
    created_at: datetime


class UpcomingAppointmentsResponse(BaseModel):
    items: list[UpcomingAppointmentResponse]


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
# Profile
# ---------------------------------------------------------------------------


class UpdateProfileRequest(BaseModel):
    """Self-service profile update; a field absent from the payload is left unchanged."""

    display_name: str | None = Field(default=None, max_length=120)
    address: str | None = Field(default=None, max_length=500)
    phone: str | None = Field(default=None, max_length=40)
