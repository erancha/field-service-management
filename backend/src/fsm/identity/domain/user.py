"""User entity for the identity bounded context."""
from __future__ import annotations

import datetime as dt
import uuid
from dataclasses import dataclass

from fsm.identity.domain.errors import InvalidUser
from fsm.identity.domain.role import Role
from fsm.identity.domain.role_status import RoleStatus


@dataclass
class User:
    """Mutable entity representing an authenticated application user.

    Core responsibilities:
    - Holds the stable Google subject identifier linking this record to a Google account
    - Tracks the user's email, display name, and assigned role plus its approval status
    - Enforces construction invariants and role transitions

    google_sub is the immutable external identity key issued by Google; it never
    changes for a given Google account even if the email address is updated.

    role and role_status are orthogonal: role is the access the user is claiming, role_status
    whether that access is granted. role_decided_at / role_decided_by record the administrator
    decision that last set role_status (both None until a decision is made).

    display_name, address, and phone are self-service profile fields; sign-in reconciliation
    syncs only email and name from Google claims, so these survive every re-sign-in.

    assist_disclaimer_accepted_at records when the user confirmed they understand what the triage
    assistant is; None until they do.
    """

    id: uuid.UUID
    google_sub: str
    email: str
    name: str
    role: Role
    role_status: RoleStatus
    role_decided_at: dt.datetime | None = None
    role_decided_by: uuid.UUID | None = None
    display_name: str | None = None
    address: str | None = None
    phone: str | None = None
    assist_disclaimer_accepted_at: dt.datetime | None = None

    def __post_init__(self) -> None:
        if not self.google_sub:
            raise InvalidUser("google_sub must not be empty.")
        if not self.email:
            raise InvalidUser("email must not be empty.")

    @property
    def preferred_name(self) -> str:
        """Name to render for this user: the self-chosen display name when set, else the
        Google-synced name."""
        return self.display_name or self.name

    @property
    def is_approved_technician(self) -> bool:
        """True when the user holds an APPROVED TECHNICIAN role — the only users who may be
        offered in customer-facing availability or targeted by a booking."""
        return self.role is Role.TECHNICIAN and self.role_status is RoleStatus.APPROVED

    def accept_assist_disclaimer(self, at: dt.datetime) -> None:
        """Record that the user accepted the assistant disclaimer, keeping the first acceptance.

        assist_disclaimer_accepted_at answers when the user first agreed, so a repeated
        acceptance — a reload, a second tab — must not move it forward.
        """
        if self.assist_disclaimer_accepted_at is None:
            self.assist_disclaimer_accepted_at = at

    def grant_role(self, role: Role) -> None:
        """Assign a role with immediate effect, clearing any prior decision.

        Used for access that needs no approval (customer self-service, the env-bootstrapped
        administrator): the role is APPROVED at once and stale decision stamps are dropped.
        """
        self.role = role
        self.role_status = RoleStatus.APPROVED
        self.role_decided_at = None
        self.role_decided_by = None

    def request_role(self, role: Role) -> None:
        """Claim a role that requires back-office approval, leaving it PENDING."""
        self.role = role
        self.role_status = RoleStatus.PENDING
        self.role_decided_at = None
        self.role_decided_by = None

    def approve(self, decided_by: uuid.UUID, at: dt.datetime) -> None:
        """Grant the currently-claimed role, recording who approved it and when."""
        self.role_status = RoleStatus.APPROVED
        self.role_decided_by = decided_by
        self.role_decided_at = at

    def reject(self, decided_by: uuid.UUID, at: dt.datetime) -> None:
        """Decline the currently-claimed role, recording who rejected it and when."""
        self.role_status = RoleStatus.REJECTED
        self.role_decided_by = decided_by
        self.role_decided_at = at
