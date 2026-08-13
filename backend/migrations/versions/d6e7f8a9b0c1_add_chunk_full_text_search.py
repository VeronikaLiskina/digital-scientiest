"""add chunk full text search

Revision ID: d6e7f8a9b0c1
Revises: c5d6e7f8a9b0
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "d6e7f8a9b0c1"
down_revision: Union[str, Sequence[str], None] = "c5d6e7f8a9b0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


SEARCH_VECTOR_EXPRESSION = (
    "setweight(to_tsvector('russian', coalesce(chunk_text, '')), 'A') || "
    "setweight(to_tsvector('simple', coalesce(chunk_text, '')), 'B')"
)


def upgrade() -> None:
    op.add_column(
        "document_chunks",
        sa.Column(
            "search_vector",
            postgresql.TSVECTOR(),
            sa.Computed(SEARCH_VECTOR_EXPRESSION, persisted=True),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_document_chunks_search_vector_gin",
        "document_chunks",
        ["search_vector"],
        postgresql_using="gin",
    )


def downgrade() -> None:
    op.drop_index(
        "ix_document_chunks_search_vector_gin",
        table_name="document_chunks",
    )
    op.drop_column("document_chunks", "search_vector")
