from enum import Enum


class RoleStatus(str, Enum):
    """Approval state of a user's assigned role.

    Orthogonal to Role: a user is some role (what access they are claiming) and that role
    is in some status (whether the access is granted). Effective access requires APPROVED.
    PENDING marks a technician awaiting back-office approval; REJECTED is sticky so a declined
    person is not re-queued by repeated technician-host sign-ins.
    """

    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
