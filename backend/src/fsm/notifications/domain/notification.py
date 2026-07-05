"""Notification domain model for the in-app feed."""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime
from enum import Enum


class NotificationKind(str, Enum):
    BOOKED = "BOOKED"
    RESCHEDULED = "RESCHEDULED"
    UPDATED = "UPDATED"
    CANCELLED = "CANCELLED"


@dataclass(frozen=True)
class Notification:
    """Immutable record representing a single in-app notification for one user.

    Each appointment lifecycle event produces one Notification per affected party
    (customer and technician). read reflects the unread state at construction time;
    the persisted read flag is updated in place on the stored row via the feed
    repository's mark_read, not on this immutable entity.
    """

    id: uuid.UUID
    user_id: uuid.UUID
    kind: NotificationKind
    subject: str
    body: str
    created_at: datetime
    read: bool = False
