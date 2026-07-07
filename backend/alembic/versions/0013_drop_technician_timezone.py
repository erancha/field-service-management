"""Drop the technician_timezone table.

The application operates in a single service-region timezone configured via Settings.timezone
(the TIMEZONE env var), so per-technician timezone rows are no longer read or written.

Revision ID: 0013
Revises: 0012
Create Date: 2026-07-07

"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision: str = "0013"
down_revision: Union[str, None] = "0012"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_table("technician_timezone")


def downgrade() -> None:
    op.create_table(
        "technician_timezone",
        sa.Column("technician_id", UUID(as_uuid=True), nullable=False),
        sa.Column("timezone", sa.Text(), nullable=False),
        sa.PrimaryKeyConstraint("technician_id"),
    )
