"""Add appointment_audit table for the append-only transition log.

Revision ID: 0007
Revises: 0006
Create Date: 2026-06-26

"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import TIMESTAMP, UUID

revision: str = "0007"
down_revision: Union[str, None] = "0006"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "appointment_audit",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("appointment_id", UUID(as_uuid=True), nullable=False),
        sa.Column("action", sa.String, nullable=False),
        sa.Column("occurred_at", TIMESTAMP(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_appointment_audit_appointment_id",
        "appointment_audit",
        ["appointment_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_appointment_audit_appointment_id", table_name="appointment_audit")
    op.drop_table("appointment_audit")
