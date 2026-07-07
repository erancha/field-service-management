"""Port for the in-app notification feed repository."""
from __future__ import annotations

import uuid
from typing import Protocol, runtime_checkable

from fsm.notifications.domain.notification import Notification, NotificationEvent


@runtime_checkable
class NotificationFeedRepository(Protocol):
    """Outbound port for persisting and querying the per-user notification feed."""

    def add_event(self, event: NotificationEvent, user_ids: list[uuid.UUID]) -> None:
        """Persist one shared event and a recipient row for each of user_ids."""
        ...

    def list_for_user(
        self,
        user_id: uuid.UUID,
        *,
        unread_only: bool = False,
    ) -> list[Notification]:
        """Return notifications for a user, optionally filtered to unread ones only."""
        ...

    def mark_read(self, recipient_id: uuid.UUID) -> None:
        """Flip the read flag to True for the given recipient id."""
        ...
