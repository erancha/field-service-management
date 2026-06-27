"""Add role_status and decision-audit columns to app_user.

Splits a user's role (the access claimed) from its approval state (whether the access is granted),
so a technician awaiting back-office approval is never mislabeled an effective role. Existing users
are backfilled to APPROVED because their roles predate the approval workflow and are already
legitimate; the server default is then dropped so the application owns the value going forward.

Revision ID: 0011
Revises: 0010
Create Date: 2026-06-26

"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import TIMESTAMP, UUID

revision: str = "0011"
down_revision: Union[str, None] = "0010"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "app_user",
        sa.Column("role_status", sa.Text, nullable=False, server_default="APPROVED"),
    )
    op.add_column(
        "app_user",
        sa.Column("role_decided_at", TIMESTAMP(timezone=True), nullable=True),
    )
    op.add_column(
        "app_user",
        sa.Column("role_decided_by", UUID(as_uuid=True), nullable=True),
    )
    op.alter_column("app_user", "role_status", server_default=None)


def downgrade() -> None:
    op.drop_column("app_user", "role_decided_by")
    op.drop_column("app_user", "role_decided_at")
    op.drop_column("app_user", "role_status")
