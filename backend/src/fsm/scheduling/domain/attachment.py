"""Photo attachments a service call inherits from its triage conversation."""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class ServiceCallAttachment:
    """A customer photo carried over from triage; the original lives in object storage under
    object_key."""

    id: uuid.UUID
    service_call_id: uuid.UUID
    filename: str
    media_type: str
    size_bytes: int
    object_key: str
    created_at: datetime
