"""Rate-limit policy for a customer's book/cancel churn."""
from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime, timedelta


@dataclass(frozen=True)
class CancellationRateLimit:
    """Caps how often a single customer may cancel appointments before booking is paused.

    max_cancellations: cancellations inside the rolling window that trigger the pause.
    window: rolling period the cancellations are counted over, ending at "now".
    cooloff: how long booking stays paused, measured from the customer's latest cancellation.
    """

    max_cancellations: int
    window: timedelta
    cooloff: timedelta

    def __post_init__(self) -> None:
        if self.max_cancellations < 1:
            raise ValueError(f"max_cancellations must be >= 1, got {self.max_cancellations}")
        if self.window <= timedelta(0) or self.cooloff <= timedelta(0):
            raise ValueError(
                f"window and cooloff must be positive, got window={self.window} "
                f"cooloff={self.cooloff}"
            )

    def blocked_until(self, cancellations: Iterable[datetime], now: datetime) -> datetime | None:
        """Return when booking reopens, or None when booking is allowed now.

        Booking is paused while at least max_cancellations of the given cancellation
        times fall inside [now - window, now] and the cooloff since the most recent
        one has not yet elapsed.
        """
        recent = [t for t in cancellations if t >= now - self.window]
        if len(recent) < self.max_cancellations:
            return None
        retry_at = max(recent) + self.cooloff
        return retry_at if retry_at > now else None
