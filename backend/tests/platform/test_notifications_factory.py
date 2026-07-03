"""Unit tests for the notifications factory's guarded context resolver."""
from __future__ import annotations

import uuid
from dataclasses import dataclass


class _RaisingSession:
    """Stands in for a SQLAlchemy session whose get() always fails."""

    def get(self, *args, **kwargs):
        raise RuntimeError("db down")


class _FakeSession:
    """Session stub whose get(RowType, id) returns a pre-seeded row (keyed by type name + id)."""

    def __init__(self, rows: dict) -> None:
        self._rows = rows

    def get(self, row_type, id_):
        return self._rows.get((row_type.__name__, id_))


class _NoSmtpSettings:
    """Settings stub with SMTP unconfigured, forcing the LoggingEmailSender fallback."""

    smtp_host = None
    smtp_sender_address = None


@dataclass
class _AppointmentStub:
    id: uuid.UUID
    service_call_id: uuid.UUID
    customer_id: uuid.UUID
    technician_id: uuid.UUID


def test_context_resolver_placeholders_required_fields_and_logs_on_lookup_failure(
    caplog,
) -> None:
    import logging

    from fsm.platform.notifications_factory import build_notifications

    port = build_notifications(session=_RaisingSession(), settings=_NoSmtpSettings())
    appointment = _AppointmentStub(
        id=uuid.uuid4(),
        service_call_id=uuid.uuid4(),
        customer_id=uuid.uuid4(),
        technician_id=uuid.uuid4(),
    )

    with caplog.at_level(logging.WARNING):
        context = port._context_resolver(appointment)

    # Required customer-facing fields surface a visible placeholder rather than being dropped.
    assert context.customer_name == "[customer name missing]"
    assert context.problem_description == "[problem missing]"
    assert context.technician_name == "[technician name missing]"
    assert context.technician_phone == "[technician phone missing]"
    # The customer's own address/phone are not required on the customer surface; they stay absent.
    assert context.service_address is None
    assert context.customer_phone is None
    messages = [r.getMessage() for r in caplog.records]
    assert any(str(appointment.service_call_id) in m for m in messages)
    assert any(str(appointment.customer_id) in m for m in messages)


def test_context_resolver_populates_technician_name_and_phone_from_technician_profile() -> None:
    from fsm.identity.adapters.orm import UserRow
    from fsm.identity.domain.role import Role
    from fsm.identity.domain.role_status import RoleStatus
    from fsm.platform.notifications_factory import build_notifications
    from fsm.scheduling.adapters.orm import ServiceCallRow

    cust_id, tech_id, sc_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()

    def _user_row(uid, name, **profile):
        return UserRow(
            id=uid,
            google_sub=f"sub-{uid}",
            email=f"{uid}@example.com",
            name=name,
            role=Role.CUSTOMER.value,
            role_status=RoleStatus.APPROVED.value,
            **profile,
        )

    session = _FakeSession({
        ("UserRow", cust_id): _user_row(cust_id, "Ada Lovelace", address="12 Main St", phone="+972-50-123"),
        ("UserRow", tech_id): _user_row(tech_id, "Grace Hopper", phone="+972-50-999"),
        ("ServiceCallRow", sc_id): ServiceCallRow(
            id=sc_id, customer_id=cust_id, description="No hot water", status="OPEN",
        ),
    })
    port = build_notifications(session=session, settings=_NoSmtpSettings())
    appointment = _AppointmentStub(
        id=uuid.uuid4(), service_call_id=sc_id, customer_id=cust_id, technician_id=tech_id
    )

    context = port._context_resolver(appointment)

    assert context.customer_name == "Ada Lovelace"
    assert context.problem_description == "No hot water"
    assert context.service_address == "12 Main St"
    assert context.customer_phone == "+972-50-123"
    assert context.technician_name == "Grace Hopper"
    assert context.technician_phone == "+972-50-999"


def test_factory_passes_smtp_sender_as_organizer_address() -> None:
    from fsm.platform.notifications_factory import build_notifications

    class _Settings:
        smtp_host = None
        smtp_sender_address = "ops@fsm.example"

    port = build_notifications(session=_RaisingSession(), settings=_Settings())
    assert port._organizer_address == "ops@fsm.example"


class _StoredTimezoneSession:
    """Session stub whose working-hours timezone query yields a fixed stored zone."""

    def __init__(self, tz: str) -> None:
        self._tz = tz

    def query(self, row_type):
        return self

    def filter(self, *args):
        return self

    def first(self):
        from types import SimpleNamespace

        return SimpleNamespace(timezone=self._tz)


def test_local_zone_uses_the_technician_stored_timezone() -> None:
    import zoneinfo

    from fsm.platform.notifications_factory import build_notifications

    port = build_notifications(
        session=_StoredTimezoneSession("Europe/London"), settings=_NoSmtpSettings()
    )

    assert port._local_zone(uuid.uuid4()) == zoneinfo.ZoneInfo("Europe/London")


def test_local_zone_degrades_to_the_region_default_when_the_read_fails(caplog) -> None:
    import logging
    import zoneinfo

    from fsm.platform.config import DEFAULT_TIMEZONE
    from fsm.platform.notifications_factory import build_notifications

    port = build_notifications(session=_RaisingSession(), settings=_NoSmtpSettings())

    with caplog.at_level(logging.ERROR):
        zone = port._local_zone(uuid.uuid4())

    assert zone == zoneinfo.ZoneInfo(DEFAULT_TIMEZONE)
    assert any("Timezone lookup failed" in r.getMessage() for r in caplog.records)
