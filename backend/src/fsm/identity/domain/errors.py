"""Domain exception hierarchy for the identity bounded context."""


class IdentityError(Exception):
    """Base class for all identity domain errors."""


class InvalidUser(IdentityError):
    """Raised when a User is constructed or mutated with invalid field values."""


class AuthenticationError(IdentityError):
    """Raised when a credential is invalid, expired, or unrecognised."""


class NotFoundError(IdentityError):
    """Raised when a repository lookup finds no entity matching the requested id."""


class DuplicateGoogleSub(IdentityError):
    """Raised by the repository when an add() would violate the google_sub uniqueness constraint.

    The sign-in use-case catches this to resolve a concurrent first-sign-in race: the
    concurrent insert already committed, so re-fetching by google_sub returns the winner.
    """


class BackOfficeAccessDenied(IdentityError):
    """Raised when a sign-in on the back-office host is not on the administrator allowlist.

    No privileged role is assigned and no new user is persisted; an existing user keeps the role
    they already held. The API layer maps this to 403.
    """


class InvalidRoleDecision(IdentityError):
    """Raised when an approve/reject targets a user who is not a pending technician.

    Approval decisions apply only to a TECHNICIAN whose role_status is PENDING; anything else
    (a customer, an already-decided technician) is a no-op the back office should never request.
    """
