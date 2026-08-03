"""The deployments this backend serves, and what each one is.

One entry per FSM_ROLE: the sign-in funnel a completed sign-in on that role's host grants, and the
background workers its process owns. A deployment has one or the other — the three role processes
serve HTTP and run no loops, while the worker deployment runs the loops and serves nothing.
create_app composes a process out of the entry FSM_ROLE selects and worker.py composes the worker
from its entry, so a new deployment is a new entry here rather than another branch in either
composition root.
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
    """What one role's process is: the sign-in funnel it grants, or the workers it runs.

    A sign_in_host of None marks a deployment that serves no HTTP, which create_app refuses to
    build. Workers are ordered as declared, so a process starts its threads in the same order
    every time.
    """

    sign_in_host: SignInHost | None = None
    workers: tuple[Worker, ...] = ()


# Both calendar loops belong to the worker deployment, so no HTTP role carries them and every role
# process scales freely. Only the worker deployment is constrained, and only for inbound sync: two
# pollers would reconcile the same Google changes twice.
DEPLOYMENTS: dict[str, Deployment] = {
    "customer": Deployment(SignInHost.CUSTOMER),
    "technician": Deployment(SignInHost.TECHNICIAN),
    "backoffice": Deployment(SignInHost.BACKOFFICE),
    "worker": Deployment(workers=(Worker.CALENDAR_DISPATCH, Worker.INBOUND_SYNC)),
}

# Roles create_app will build: those that grant a sign-in funnel.
SERVING_ROLES = tuple(
    role for role, deployment in DEPLOYMENTS.items() if deployment.sign_in_host is not None
)
