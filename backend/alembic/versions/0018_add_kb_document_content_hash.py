"""Store a unique SHA-256 hash of each document's bytes so a byte-identical re-upload is rejected."""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0018"
down_revision: Union[str, None] = "0017"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Deployed knowledge bases are still disposable, so dropping the stored documents is cheaper
    # than backfilling a hash per row, and lets the column arrive NOT NULL outright. kb_chunk
    # holds the chunks derived from the dropped rows; the vector store creates it lazily outside
    # Alembic, hence dropped only if present.
    op.execute("DELETE FROM kb_document")
    op.execute("DROP TABLE IF EXISTS kb_chunk")
    op.add_column("kb_document", sa.Column("content_sha256", sa.Text(), nullable=False))
    op.create_index(
        "uq_kb_document_content_sha256", "kb_document", ["content_sha256"], unique=True
    )


def downgrade() -> None:
    op.drop_index("uq_kb_document_content_sha256", table_name="kb_document")
    op.drop_column("kb_document", "content_sha256")
