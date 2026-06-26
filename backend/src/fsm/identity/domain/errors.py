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
