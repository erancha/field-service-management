"""Unit tests for the dispatcher's customer-context resolver and its required-field rule.

Exercises build_customer_context_resolver against a fake session factory so no database is
needed; the resolver feeds the technician's Google-event projection.
"""
from __future__ import annotations

import logging
import uuid

from fsm.identity.adapters.orm import UserRow
from fsm.identity.domain.role import Role
from fsm.identity.domain.role_status import RoleStatus
from fsm.platform.dispatcher_runner import (
    build_customer_context_resolver,
    build_technician_context_resolver,
)


def _session_factory(rows: dict):
    class _Session:
        def get(self, row_type, id_):
            return rows.get((row_type.__name__, id_))

    class _Ctx:
        def __enter__(self):
            return _Session()

        def __exit__(self, *exc):
            return False

    return lambda: _Ctx()


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


def test_populates_customer_profile_fields_when_present() -> None:
    cust_id = uuid.uuid4()
    resolve = build_customer_context_resolver(
        _session_factory({("UserRow", cust_id): _user_row(
            cust_id, "Ada Lovelace", address="  12 Main St  ", phone="+972-50-123"
        )})
    )

    ctx = resolve(cust_id)

    assert ctx.customer_name == "Ada Lovelace"
    assert ctx.service_address == "12 Main St"
    assert ctx.customer_phone == "+972-50-123"


def test_missing_customer_fields_placeholder_and_warn(caplog) -> None:
    cust_id = uuid.uuid4()
    resolve = build_customer_context_resolver(_session_factory({}))

    with caplog.at_level(logging.WARNING):
        ctx = resolve(cust_id)

    assert ctx.customer_name == "[customer name missing]"
    assert ctx.service_address == "[service address missing]"
    assert ctx.customer_phone == "[customer phone missing]"


def test_populates_technician_name_and_phone_when_present() -> None:
    tech_id = uuid.uuid4()
    resolve = build_technician_context_resolver(
        _session_factory({("UserRow", tech_id): _user_row(
            tech_id, "Grace Hopper", phone="+972-50-999"
        )})
    )

    ctx = resolve(tech_id)

    assert ctx.technician_name == "Grace Hopper"
    assert ctx.technician_phone == "+972-50-999"
    # This resolver only fills the technician's own fields; customer fields stay unset here.
    assert ctx.customer_name is None


def test_missing_technician_fields_placeholder_and_warn(caplog) -> None:
    tech_id = uuid.uuid4()
    resolve = build_technician_context_resolver(_session_factory({}))

    with caplog.at_level(logging.WARNING):
        ctx = resolve(tech_id)

    assert ctx.technician_name == "[technician name missing]"
    assert ctx.technician_phone == "[technician phone missing]"
