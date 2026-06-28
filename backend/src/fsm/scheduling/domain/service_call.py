"""ServiceCall entity representing a customer request for field service."""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum

from fsm.scheduling.domain.errors import InvalidTransition


class ServiceCallStatus(str, Enum):
    OPEN = "OPEN"
    SCHEDULED = "SCHEDULED"
    CANCELLED = "CANCELLED"


@dataclass
class ServiceCall:
    """Mutable entity tracking a customer's service request through its lifecycle.

    Lifecycle: OPEN → SCHEDULED (via mark_scheduled).
    """

    id: uuid.UUID
    customer_id: uuid.UUID
    description: str
    status: ServiceCallStatus
    created_at: datetime

    def mark_scheduled(self) -> None:
        """Transition status from OPEN to SCHEDULED.

        Only valid when the current status is OPEN; raises InvalidTransition otherwise.
        """
        if self.status is not ServiceCallStatus.OPEN:
            raise InvalidTransition(
                f"Cannot schedule a service call with status {self.status.value!r}; "
                "only OPEN calls may be scheduled."
            )
        self.status = ServiceCallStatus.SCHEDULED
