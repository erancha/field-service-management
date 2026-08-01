"""Add app_user.assist_disclaimer_accepted_at, holding when a user accepted the assistant
disclaimer.

A timestamp rather than a boolean, so the column also answers when the user was told what the
assistant is and is not. Null means never accepted, so every account predating this revision is
asked on its next sign-in.

Revision ID: 0021
Revises: 0020
Create Date: 2026-08-01

"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import TIMESTAMP

revision: str = "0021"
down_revision: Union[str, None] = "0020"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "app_user",
        sa.Column("assist_disclaimer_accepted_at", TIMESTAMP(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("app_user", "assist_disclaimer_accepted_at")
