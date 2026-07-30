"""Carry customer triage photos as metadata rows: per-conversation photos and the
attachments a service call inherits on escalation."""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import TIMESTAMP, UUID

revision: str = "0019"
down_revision: Union[str, None] = "0018"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "assist_photo",
        sa.Column("id", UUID(as_uuid=True), nullable=False),
        sa.Column("conversation_id", UUID(as_uuid=True), nullable=False),
        sa.Column("message_id", UUID(as_uuid=True), nullable=True),
        sa.Column("filename", sa.Text(), nullable=False),
        sa.Column("media_type", sa.Text(), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("object_key", sa.Text(), nullable=False),
        sa.Column("created_at", TIMESTAMP(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(
            ["conversation_id"], ["assist_conversation.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["message_id"], ["assist_message.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_assist_photo_conversation", "assist_photo", ["conversation_id"])
    op.create_index("ix_assist_photo_message", "assist_photo", ["message_id"])

    op.create_table(
        "service_call_attachment",
        sa.Column("id", UUID(as_uuid=True), nullable=False),
        sa.Column("service_call_id", UUID(as_uuid=True), nullable=False),
        sa.Column("filename", sa.Text(), nullable=False),
        sa.Column("media_type", sa.Text(), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("object_key", sa.Text(), nullable=False),
        sa.Column("created_at", TIMESTAMP(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["service_call_id"], ["service_call.id"], ondelete="CASCADE"),
    )
    op.create_index(
        "ix_service_call_attachment_call", "service_call_attachment", ["service_call_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_service_call_attachment_call", table_name="service_call_attachment")
    op.drop_table("service_call_attachment")

    op.drop_index("ix_assist_photo_message", table_name="assist_photo")
    op.drop_index("ix_assist_photo_conversation", table_name="assist_photo")
    op.drop_table("assist_photo")
