"""Add self-service profile columns to app_user.

display_name, address, and phone are entered by the user (onboarding or profile page), never
synced from Google claims. All three are nullable free text: a profile is optional and renderers
fall back to generic content when it is absent.

Revision ID: 0012
Revises: 0011
Create Date: 2026-07-02

"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0012"
down_revision: Union[str, None] = "0011"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("app_user", sa.Column("display_name", sa.Text, nullable=True))
    op.add_column("app_user", sa.Column("address", sa.Text, nullable=True))
    op.add_column("app_user", sa.Column("phone", sa.Text, nullable=True))


def downgrade() -> None:
    op.drop_column("app_user", "phone")
    op.drop_column("app_user", "address")
    op.drop_column("app_user", "display_name")
