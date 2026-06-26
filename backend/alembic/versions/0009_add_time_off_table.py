"""Add time_off table for per-technician day-off records.

Revision ID: 0009
Revises: 0008
Create Date: 2026-06-26

"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision: str = "0009"
down_revision: Union[str, None] = "0008"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "time_off",
        sa.Column("technician_id", UUID(as_uuid=True), nullable=False),
        sa.Column("off_date", sa.Date(), nullable=False),
        sa.PrimaryKeyConstraint("technician_id", "off_date"),
    )


def downgrade() -> None:
    op.drop_table("time_off")
