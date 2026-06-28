"""Initial scheduling schema: service_call and appointment tables with GiST no-overlap constraint.

Revision ID: 0001
Revises:
Create Date: 2026-06-25

"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import TIMESTAMP, UUID

revision: str = "0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # btree_gist lets the GiST index mix the UUID equality operator (=) with the range
    # overlap operator (&&) in a single EXCLUDE constraint. Without it, Postgres cannot
    # build an exclusion index over a non-range column alongside a range column.
    op.execute("CREATE EXTENSION IF NOT EXISTS btree_gist;")

    op.create_table(
        "service_call",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("customer_id", UUID(as_uuid=True), nullable=False),
        sa.Column("description", sa.String, nullable=False),
        sa.Column("status", sa.String, nullable=False),
        sa.Column("created_at", TIMESTAMP(timezone=True), nullable=False),
    )

    op.create_table(
        "appointment",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("service_call_id", UUID(as_uuid=True), nullable=False),
        sa.Column("technician_id", UUID(as_uuid=True), nullable=False),
        sa.Column("customer_id", UUID(as_uuid=True), nullable=False),
        sa.Column("start_at", TIMESTAMP(timezone=True), nullable=False),
        sa.Column("end_at", TIMESTAMP(timezone=True), nullable=False),
        sa.Column("status", sa.String, nullable=False),
        sa.Column("details", sa.String, nullable=True),
        sa.Column("external_event_id", sa.String, nullable=True),
        sa.Column("created_at", TIMESTAMP(timezone=True), nullable=False),
        sa.Column("updated_at", TIMESTAMP(timezone=True), nullable=False),
    )

    # The GiST exclusion constraint enforces that no two non-cancelled appointments for
    # the same technician overlap in time. tstzrange uses the half-open interval [start, end)
    # so back-to-back appointments that share an endpoint are allowed.
    op.execute(
        """
        ALTER TABLE appointment
            ADD CONSTRAINT appointment_no_overlap
            EXCLUDE USING gist (
                technician_id WITH =,
                tstzrange(start_at, end_at, '[)') WITH &&
            )
            WHERE (status <> 'CANCELLED')
        """
    )


def downgrade() -> None:
    op.execute("ALTER TABLE appointment DROP CONSTRAINT IF EXISTS appointment_no_overlap;")
    op.drop_table("appointment")
    op.drop_table("service_call")
    op.execute("DROP EXTENSION IF EXISTS btree_gist;")
