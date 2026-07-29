"""The pgvector extension is installed by migrations, so vector columns are available."""
from sqlalchemy import text


def test_vector_extension_is_installed(pg_engine):
    with pg_engine.connect() as conn:
        installed = conn.execute(
            text("SELECT count(*) FROM pg_extension WHERE extname = 'vector'")
        ).scalar_one()
    assert installed == 1
