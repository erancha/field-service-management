"""Notification domain model for the in-app feed."""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime
from enum import Enum


class NotificationKind(str, Enum):
    BOOKED = "BOOKED"
    RESCHEDULED = "RESCHEDULED"
    RESCHEDULE_REJECTED = "RESCHEDULE_REJECTED"
    UPDATED = "UPDATED"
    CANCELLED = "CANCELLED"


@dataclass(frozen=True)
class NotificationEvent:
    """Immutable content of one appointment lifecycle event, shared by all recipients.

    A single event fans out to every affected party (customer and technician), who each read
    the identical subject and body carried here.
    """

    id: uuid.UUID
    kind: NotificationKind
    subject: str
    body: str
    created_at: datetime


@dataclass(frozen=True)
class Notification:
    """Immutable per-recipient view of a notification event for one user.

    id is the recipient's own identifier — the handle mark_read targets to flip that user's
    read flag without affecting the other recipient of the same event. read reflects the unread
    state at construction time; the persisted flag is updated in place on the stored recipient
    row via the feed repository's mark_read, not on this immutable entity.
    """

    id: uuid.UUID
    user_id: uuid.UUID
    kind: NotificationKind
    subject: str
    body: str
    created_at: datetime
    read: bool = False
