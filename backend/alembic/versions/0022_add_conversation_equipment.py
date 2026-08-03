"""Add assist_conversation.equipment, holding what the assistant determined the machine to be.

The knowledge-base query is built from this identity plus the customer's message, so a follow-up
naming no equipment of its own still retrieves against the right manual. Null means triage has not
identified it yet, which is where every conversation starts and where conversations predating this
revision stay.

Revision ID: 0022
Revises: 0021
Create Date: 2026-08-03

"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0022"
down_revision: Union[str, None] = "0021"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("assist_conversation", sa.Column("equipment", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("assist_conversation", "equipment")
