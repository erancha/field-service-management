"""Store triage conversations and their turns; the chat rehydrates from these rows."""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import TIMESTAMP, UUID

revision: str = "0017"
down_revision: Union[str, None] = "0016"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "assist_conversation",
        sa.Column("id", UUID(as_uuid=True), nullable=False),
        sa.Column("customer_id", UUID(as_uuid=True), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("service_call_id", UUID(as_uuid=True), nullable=True),
        sa.Column("created_at", TIMESTAMP(timezone=True), nullable=False),
        sa.Column("updated_at", TIMESTAMP(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_assist_conversation_customer_status",
        "assist_conversation",
        ["customer_id", "status"],
    )
    op.create_index(
        "uq_assist_conversation_one_active_per_customer",
        "assist_conversation",
        ["customer_id"],
        unique=True,
        postgresql_where=sa.text("status = 'ACTIVE'"),
    )
    op.create_table(
        "assist_message",
        sa.Column("id", UUID(as_uuid=True), nullable=False),
        sa.Column("conversation_id", UUID(as_uuid=True), nullable=False),
        sa.Column("seq", sa.Integer(), nullable=False),
        sa.Column("role", sa.Text(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("created_at", TIMESTAMP(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(
            ["conversation_id"], ["assist_conversation.id"], ondelete="CASCADE"
        ),
    )
    op.create_index(
        "ix_assist_message_conversation_seq",
        "assist_message",
        ["conversation_id", "seq"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("ix_assist_message_conversation_seq", table_name="assist_message")
    op.drop_table("assist_message")
    op.drop_index(
        "uq_assist_conversation_one_active_per_customer", table_name="assist_conversation"
    )
    op.drop_index("ix_assist_conversation_customer_status", table_name="assist_conversation")
    op.drop_table("assist_conversation")
