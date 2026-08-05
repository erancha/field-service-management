"""Add assist_conversation.triage_declined, the customer's standing choice to skip troubleshooting.

Each turn rebuilds the assistant's instructions from the stored conversation, so a request to skip
straight to a technician must survive the turn that voiced it — including a turn retried after a
provider failure. False means normal triage, which is where every conversation starts and where
conversations predating this revision stay.

Revision ID: 0023
Revises: 0022
Create Date: 2026-08-05

"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0023"
down_revision: Union[str, None] = "0022"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "assist_conversation",
        sa.Column(
            "triage_declined", sa.Boolean(), nullable=False, server_default=sa.text("false")
        ),
    )


def downgrade() -> None:
    op.drop_column("assist_conversation", "triage_declined")
