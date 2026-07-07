"""SQLAlchemy adapter for the NotificationFeedRepository port."""
from __future__ import annotations

import uuid

from sqlalchemy.orm import Session

from fsm.notifications.adapters.orm import NotificationEventRow, NotificationRecipientRow
from fsm.notifications.domain.notification import (
    Notification,
    NotificationEvent,
    NotificationKind,
)


def _to_notification(recipient: NotificationRecipientRow, event: NotificationEventRow) -> Notification:
    return Notification(
        id=recipient.id,
        user_id=recipient.user_id,
        kind=NotificationKind(event.kind),
        subject=event.subject,
        body=event.body,
        created_at=event.created_at,
        read=recipient.read,
    )


class SqlAlchemyNotificationFeedRepository:
    """Session-scoped repository for the notification event and recipient tables."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def add_event(self, event: NotificationEvent, user_ids: list[uuid.UUID]) -> None:
        """Insert one event row and a recipient row per user id. Caller owns the transaction."""
        self._session.add(
            NotificationEventRow(
                id=event.id,
                kind=event.kind.value,
                subject=event.subject,
                body=event.body,
                created_at=event.created_at,
            )
        )
        for user_id in user_ids:
            self._session.add(
                NotificationRecipientRow(
                    id=uuid.uuid4(),
                    notification_event_id=event.id,
                    user_id=user_id,
                )
            )
        self._session.flush()

    def list_for_user(
        self,
        user_id: uuid.UUID,
        *,
        unread_only: bool = False,
    ) -> list[Notification]:
        """Return notifications for a user ordered by event created_at descending."""
        query = (
            self._session.query(NotificationRecipientRow, NotificationEventRow)
            .join(
                NotificationEventRow,
                NotificationRecipientRow.notification_event_id == NotificationEventRow.id,
            )
            .filter(NotificationRecipientRow.user_id == user_id)
        )
        if unread_only:
            query = query.filter(NotificationRecipientRow.read == False)  # noqa: E712
        rows = query.order_by(NotificationEventRow.created_at.desc()).all()
        return [_to_notification(recipient, event) for recipient, event in rows]

    def mark_read(self, recipient_id: uuid.UUID) -> None:
        """Set read=True for the given recipient id. No-op if not found."""
        row = self._session.get(NotificationRecipientRow, recipient_id)
        if row is not None:
            row.read = True
            self._session.flush()
