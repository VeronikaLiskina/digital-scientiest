"""add embedding to document chunks

Revision ID: 08d92809402a
Revises: c8d9e0f1a2b3
Create Date: 2026-06-26 21:56:43.114135

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from pgvector.sqlalchemy import Vector


# revision identifiers, used by Alembic.
revision: str = '08d92809402a'
down_revision: Union[str, Sequence[str], None] = 'c8d9e0f1a2b3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


EMBEDDING_DIM = 768


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    op.alter_column(
        "document_chunks",
        "embedding",
        existing_type=postgresql.JSONB(),
        type_=Vector(EMBEDDING_DIM),
        postgresql_using=f"NULL::vector({EMBEDDING_DIM})",
        nullable=True,
    )

    op.add_column(
        "document_chunks",
        sa.Column("embedding_model", sa.String(length=255), nullable=True),
    )

    op.add_column(
        "document_chunks",
        sa.Column("embedded_at", sa.DateTime(timezone=True), nullable=True),
    )

    op.create_index(
        "ix_document_chunks_embedding_hnsw",
        "document_chunks",
        ["embedding"],
        postgresql_using="hnsw",
        postgresql_ops={"embedding": "vector_cosine_ops"},
    )


def downgrade() -> None:
    op.drop_index(
        "ix_document_chunks_embedding_hnsw",
        table_name="document_chunks",
    )

    op.drop_column("document_chunks", "embedded_at")
    op.drop_column("document_chunks", "embedding_model")

    op.alter_column(
        "document_chunks",
        "embedding",
        existing_type=Vector(EMBEDDING_DIM),
        type_=postgresql.JSONB(),
        postgresql_using="embedding::text::jsonb",
        nullable=True,
    )
