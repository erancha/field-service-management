"""Add app_user table for identity bounded context.

Revision ID: 0002
Revises: 0001
Create Date: 2026-06-25

"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision: str = "0002"
down_revision: Union[str, None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "app_user",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("google_sub", sa.String, nullable=False),
        sa.Column("email", sa.String, nullable=False),
        sa.Column("name", sa.String, nullable=False),
        sa.Column("role", sa.String, nullable=False),
        sa.UniqueConstraint("google_sub", name="uq_app_user_google_sub"),
    )
    op.create_index("ix_app_user_google_sub", "app_user", ["google_sub"])


def downgrade() -> None:
    op.drop_index("ix_app_user_google_sub", table_name="app_user")
    op.drop_table("app_user")
