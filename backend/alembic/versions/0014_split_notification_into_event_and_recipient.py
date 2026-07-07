"""Split notification into notification_event and notification_recipient.

Revision ID: 0014
Revises: 0013
Create Date: 2026-07-07

"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import TIMESTAMP, UUID

revision: str = "0014"
down_revision: Union[str, None] = "0013"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "notification_event",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("kind", sa.Text, nullable=False),
        sa.Column("subject", sa.Text, nullable=False),
        sa.Column("body", sa.Text, nullable=False),
        sa.Column("created_at", TIMESTAMP(timezone=True), nullable=False),
    )
    op.create_table(
        "notification_recipient",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column(
            "notification_event_id",
            UUID(as_uuid=True),
            sa.ForeignKey("notification_event.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("user_id", UUID(as_uuid=True), nullable=False),
        sa.Column("read", sa.Boolean, nullable=False, server_default="false"),
        sa.UniqueConstraint(
            "notification_event_id", "user_id", name="uq_notification_recipient"
        ),
    )
    op.create_index(
        "ix_notification_recipient_event_id",
        "notification_recipient",
        ["notification_event_id"],
    )
    op.create_index(
        "ix_notification_recipient_user_id",
        "notification_recipient",
        ["user_id"],
    )

    # Reconstruct events by collapsing each group of byte-identical notification rows into one
    # event, then re-hang every original row as a recipient. The old notification.id is reused
    # as the recipient id so any external reference to it stays valid.
    op.execute(
        """
        INSERT INTO notification_event (id, kind, subject, body, created_at)
        SELECT gen_random_uuid(), kind, subject, body, created_at
        FROM notification
        GROUP BY kind, subject, body, created_at
        """
    )
    op.execute(
        """
        INSERT INTO notification_recipient (id, notification_event_id, user_id, read)
        SELECT n.id, e.id, n.user_id, n.read
        FROM notification n
        JOIN notification_event e
          ON e.kind = n.kind
         AND e.subject = n.subject
         AND e.body = n.body
         AND e.created_at = n.created_at
        """
    )

    op.drop_index("ix_notification_user_id", table_name="notification")
    op.drop_table("notification")


def downgrade() -> None:
    op.create_table(
        "notification",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("user_id", UUID(as_uuid=True), nullable=False),
        sa.Column("kind", sa.Text, nullable=False),
        sa.Column("subject", sa.Text, nullable=False),
        sa.Column("body", sa.Text, nullable=False),
        sa.Column("created_at", TIMESTAMP(timezone=True), nullable=False),
        sa.Column("read", sa.Boolean, nullable=False, server_default="false"),
    )
    op.create_index("ix_notification_user_id", "notification", ["user_id"])

    op.execute(
        """
        INSERT INTO notification (id, user_id, kind, subject, body, created_at, read)
        SELECT r.id, r.user_id, e.kind, e.subject, e.body, e.created_at, r.read
        FROM notification_recipient r
        JOIN notification_event e ON e.id = r.notification_event_id
        """
    )

    op.drop_index(
        "ix_notification_recipient_user_id", table_name="notification_recipient"
    )
    op.drop_index(
        "ix_notification_recipient_event_id", table_name="notification_recipient"
    )
    op.drop_table("notification_recipient")
    op.drop_table("notification_event")
