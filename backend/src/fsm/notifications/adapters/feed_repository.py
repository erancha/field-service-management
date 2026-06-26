"""SQLAlchemy adapter for the NotificationFeedRepository port."""
from __future__ import annotations

import uuid

from sqlalchemy.orm import Session

from fsm.notifications.adapters.orm import NotificationRow
from fsm.notifications.domain.notification import Notification, NotificationKind


def _row_to_notification(row: NotificationRow) -> Notification:
    return Notification(
        id=row.id,
        user_id=row.user_id,
        kind=NotificationKind(row.kind),
        subject=row.subject,
        body=row.body,
        created_at=row.created_at,
        read=row.read,
    )


class SqlAlchemyNotificationFeedRepository:
    """Session-scoped repository for the notification feed table."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def add(self, notification: Notification) -> None:
        """Insert a new notification row. Caller owns the transaction."""
        row = NotificationRow(
            id=notification.id,
            user_id=notification.user_id,
            kind=notification.kind.value,
            subject=notification.subject,
            body=notification.body,
            created_at=notification.created_at,
            read=notification.read,
        )
        self._session.add(row)
        self._session.flush()

    def list_for_user(
        self,
        user_id: uuid.UUID,
        *,
        unread_only: bool = False,
    ) -> list[Notification]:
        """Return notifications for a user ordered by created_at descending."""
        query = self._session.query(NotificationRow).filter(
            NotificationRow.user_id == user_id
        )
        if unread_only:
            query = query.filter(NotificationRow.read == False)  # noqa: E712
        rows = query.order_by(NotificationRow.created_at.desc()).all()
        return [_row_to_notification(r) for r in rows]

    def mark_read(self, notification_id: uuid.UUID) -> None:
        """Set read=True for the given notification id. No-op if not found."""
        row = self._session.get(NotificationRow, notification_id)
        if row is not None:
            row.read = True
            self._session.flush()
