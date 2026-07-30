"""Outbound port for opening a service call when triage escalates.

Assist may not import scheduling, so escalation is expressed as this interface and implemented
by the composition root over the scheduling context.
"""
from __future__ import annotations

import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from fsm.assist.domain.conversation import Photo


@dataclass(frozen=True)
class OpenedServiceCall:
    id: uuid.UUID
    description: str


@runtime_checkable
class ServiceCallOpener(Protocol):
    def open(
        self, customer_id: uuid.UUID, description: str, photos: Sequence[Photo] = ()
    ) -> OpenedServiceCall:
        """Open a service call for the customer, carrying the chat's sent photos;
        the caller commits the transaction."""
        ...
