"""baseline schema

Revision ID: 202606220001
Revises:
Create Date: 2026-06-22
"""
from typing import Sequence, Union

from alembic import op

from app.core.database import Base

revision: str = "202606220001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    Base.metadata.create_all(bind=bind)
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_document_chunks_embedding
        ON document_chunks
        USING ivfflat (embedding vector_cosine_ops)
        WITH (lists = 10)
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_document_chunks_content_fts
        ON document_chunks
        USING gin (to_tsvector('simple', content))
        """
    )


def downgrade() -> None:
    bind = op.get_bind()
    op.execute("DROP INDEX IF EXISTS idx_document_chunks_content_fts")
    op.execute("DROP INDEX IF EXISTS idx_document_chunks_embedding")
    Base.metadata.drop_all(bind=bind)
