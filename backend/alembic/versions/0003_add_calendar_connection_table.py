"""Add calendar_connection table for per-technician calendar integration.

Revision ID: 0003
Revises: 0002
Create Date: 2026-06-25

"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision: str = "0003"
down_revision: Union[str, None] = "0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "calendar_connection",
        sa.Column("technician_id", UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("fsm_calendar_id", sa.String, nullable=False),
        sa.Column("encrypted_refresh_token", sa.Text, nullable=False),
        sa.Column("status", sa.String, nullable=False),
    )


def downgrade() -> None:
    op.drop_table("calendar_connection")
