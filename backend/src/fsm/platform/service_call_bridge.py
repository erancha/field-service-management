"""Implements assist's ServiceCallOpener over the scheduling context.

Assist may not import scheduling; the composition root is the only place that sees both, so an
escalating triage conversation opens its service call through here.
"""
from __future__ import annotations

import uuid

from sqlalchemy.orm import Session

from fsm.assist.ports.service_calls import OpenedServiceCall, ServiceCallOpener
from fsm.scheduling.adapters.repositories import SqlAlchemyServiceCallRepository
from fsm.scheduling.application.service_call_service import ServiceCallService


class SchedulingServiceCallOpener:
    """Caller owns the transaction; the service call is staged on the given session."""

    def __init__(self, session: Session) -> None:
        self._service = ServiceCallService(
            service_calls=SqlAlchemyServiceCallRepository(session)
        )

    def open(self, customer_id: uuid.UUID, description: str) -> OpenedServiceCall:
        service_call = self._service.open_service_call(customer_id, description)
        return OpenedServiceCall(id=service_call.id, description=service_call.description)


def build_service_call_opener(session: Session) -> ServiceCallOpener:
    return SchedulingServiceCallOpener(session)
