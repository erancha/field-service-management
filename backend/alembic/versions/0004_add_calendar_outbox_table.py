"""Add calendar_outbox table for transactional outbox pattern.

Revision ID: 0004
Revises: 0003
Create Date: 2026-06-25

"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import TIMESTAMP, UUID

revision: str = "0004"
down_revision: Union[str, None] = "0003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "calendar_outbox",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("operation", sa.String, nullable=False),
        sa.Column("appointment_id", UUID(as_uuid=True), nullable=False),
        sa.Column("external_event_id", sa.String, nullable=True),
        sa.Column("status", sa.String, nullable=False, server_default="PENDING"),
        sa.Column("attempts", sa.Integer, nullable=False, server_default="0"),
        sa.Column(
            "created_at",
            TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("processed_at", TIMESTAMP(timezone=True), nullable=True),
        sa.Column("last_error", sa.Text, nullable=True),
    )
    op.create_index(
        "ix_calendar_outbox_status_created_at",
        "calendar_outbox",
        ["status", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_calendar_outbox_status_created_at", table_name="calendar_outbox")
    op.drop_table("calendar_outbox")
