"""Progress-reporting contract shared by the ingest ports (text extraction and indexing)."""
from __future__ import annotations

from typing import Callable

# Called with (units completed so far, total units). A reporting run leads with (0, total) as soon
# as the total is known, so a bar can turn determinate before the first unit completes. The unit is
# the reporting port's own: pages for extraction, chunks for indexing.
ProgressCallback = Callable[[int, int], None]

# Reports per run when progress is batched: enough that a bar visibly moves, few enough that a
# four-figure-unit document does not flood the event stream with one event per unit.
TARGET_PROGRESS_REPORTS = 20


def progress_step(total: int) -> int:
    """Units per progress report, sized to yield about TARGET_PROGRESS_REPORTS reports per run.

    Never below one, so the step stays usable as a range stride or modulus even for tiny runs.
    """
    return max(1, -(-total // TARGET_PROGRESS_REPORTS))
