"""Outbound port for opening a service call when triage escalates.

Assist may not import scheduling, so escalation is expressed as this interface and implemented
by the composition root over the scheduling context.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Protocol, runtime_checkable


@dataclass(frozen=True)
class OpenedServiceCall:
    id: uuid.UUID
    description: str


@runtime_checkable
class ServiceCallOpener(Protocol):
    def open(self, customer_id: uuid.UUID, description: str) -> OpenedServiceCall:
        """Open a service call for the customer; the caller commits the transaction."""
        ...
