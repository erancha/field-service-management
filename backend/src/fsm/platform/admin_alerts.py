"""Best-effort email alerts that platform flows send to the back-office administrators."""
from __future__ import annotations

import logging
from collections.abc import Iterable

from fsm.notifications.ports.email_sender import EmailSender
from fsm.shared.constants import BRAND

_log = logging.getLogger(__name__)


def send_technician_access_requested(
    email_sender: EmailSender,
    admin_emails: Iterable[str],
    *,
    requester_name: str,
    requester_email: str,
) -> None:
    """Email every back-office admin that a technician sign-in is waiting for approval.

    Each recipient is attempted independently and a failed send is logged, so a mail problem can
    neither break the sign-in that triggered the alert nor starve the remaining admins.
    """
    subject = f"{BRAND}: Technician access request — {requester_name}"
    body = (
        f"{requester_name} ({requester_email}) signed in as a technician and is waiting for"
        " approval.\n\nApprove or decline the request in the back-office approval queue."
    )
    for admin in sorted(admin_emails):
        try:
            email_sender.send(admin, subject, body)
        except Exception:
            _log.exception(
                "Technician access request alert failed for admin=%s requester=%s",
                admin,
                requester_email,
            )
