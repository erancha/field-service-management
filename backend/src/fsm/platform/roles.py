"""The deployments this backend serves, and what each one is.

One entry per FSM_ROLE: the sign-in funnel a completed sign-in on that role's host grants, and the
background workers its process owns. create_app composes a process out of the entry FSM_ROLE
selects, so a new deployment is a new entry here rather than another branch in the factory, and
which role owns the workers is a value the suite can assert instead of a convention spread across
compose, start.sh, and per-process settings.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from fsm.identity.application.identity_service import SignInHost


class Worker(Enum):
    """A background loop a deployment owns, running in one daemon thread per process.

    The value is the thread name, which is how the logs identify the loop.
    """

    CALENDAR_DISPATCH = "fsm-dispatcher"
    INBOUND_SYNC = "fsm-sync"


@dataclass(frozen=True)
class Deployment:
    """What one role's process is: the sign-in funnel it grants and the workers it runs.

    Workers are ordered as declared, so a process starts its threads in the same order every time.
    """

    sign_in_host: SignInHost
    workers: tuple[Worker, ...] = ()


# Both calendar workers belong to backoffice alone: a single owner drains the shared outbox and
# polls Google once, so a second process running either would duplicate the work and the
# notifications it produces.
DEPLOYMENTS: dict[str, Deployment] = {
    "customer": Deployment(SignInHost.CUSTOMER),
    "technician": Deployment(SignInHost.TECHNICIAN),
    "backoffice": Deployment(
        SignInHost.BACKOFFICE,
        workers=(Worker.CALENDAR_DISPATCH, Worker.INBOUND_SYNC),
    ),
}
