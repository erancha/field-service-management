"""Keep the triage assistant's summary on the service call as structure, plus the fault headline
every one-line surface shows."""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "0020"
down_revision: Union[str, None] = "0019"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Nullable in both directions: a call opened from the plain description form never has a
    # summary, and calls opened before this revision keep only the description text they were
    # written with.
    op.add_column("service_call", sa.Column("triage_summary", JSONB, nullable=True))
    op.add_column("service_call", sa.Column("headline", sa.String(), nullable=True))


def downgrade() -> None:
    op.drop_column("service_call", "headline")
    op.drop_column("service_call", "triage_summary")
