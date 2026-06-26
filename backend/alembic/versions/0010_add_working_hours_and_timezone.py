"""Add working_hours and technician_timezone tables for per-technician scheduling config.

Revision ID: 0010
Revises: 0009
Create Date: 2026-06-26

"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision: str = "0010"
down_revision: Union[str, None] = "0009"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "working_hours",
        sa.Column("technician_id", UUID(as_uuid=True), nullable=False),
        sa.Column("weekday", sa.SmallInteger(), nullable=False),
        sa.Column("start_time", sa.Time(), nullable=False),
        sa.Column("end_time", sa.Time(), nullable=False),
        sa.PrimaryKeyConstraint("technician_id", "weekday"),
    )
    op.create_table(
        "technician_timezone",
        sa.Column("technician_id", UUID(as_uuid=True), nullable=False),
        sa.Column("timezone", sa.Text(), nullable=False),
        sa.PrimaryKeyConstraint("technician_id"),
    )


def downgrade() -> None:
    op.drop_table("technician_timezone")
    op.drop_table("working_hours")
