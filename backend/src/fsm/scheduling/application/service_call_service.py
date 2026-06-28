"""Service layer for service call lifecycle management."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Callable
from uuid import UUID, uuid4

from fsm.scheduling.domain.service_call import ServiceCall, ServiceCallStatus
from fsm.scheduling.ports.repositories import ServiceCallRepository


class ServiceCallService:
    """Orchestrates service call creation for the scheduling context.

    Core responsibilities:
    - Assigns identity and timestamps to new service calls
    - Delegates persistence to the injected repository
    """

    def __init__(
        self,
        service_calls: ServiceCallRepository,
        clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
        new_id: Callable[[], UUID] = uuid4,
    ) -> None:
        self._service_calls = service_calls
        self._clock = clock
        self._new_id = new_id

    def open_service_call(
        self,
        customer_id: UUID,
        description: str,
    ) -> ServiceCall:
        """Create a new OPEN service call, persist it, and return it."""
        sc = ServiceCall(
            id=self._new_id(),
            customer_id=customer_id,
            description=description,
            status=ServiceCallStatus.OPEN,
            created_at=self._clock(),
        )
        self._service_calls.add(sc)
        return sc
