"""add publication and message fields to processing logs

Revision ID: e1f2b3c4d5e6
Revises: 08d92809402a
Create Date: 2026-06-30 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "e1f2b3c4d5e6"
down_revision: Union[str, Sequence[str], None] = "08d92809402a"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "processing_logs",
        sa.Column("publication_id", sa.Integer(), nullable=True),
    )
    op.add_column(
        "processing_logs",
        sa.Column("message", sa.Text(), nullable=True),
    )
    op.create_index(
        op.f("ix_processing_logs_publication_id"),
        "processing_logs",
        ["publication_id"],
        unique=False,
    )
    op.create_foreign_key(
        "fk_processing_logs_publication_id_publications",
        "processing_logs",
        "publications",
        ["publication_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint(
        "fk_processing_logs_publication_id_publications",
        "processing_logs",
        type_="foreignkey",
    )
    op.drop_index(op.f("ix_processing_logs_publication_id"), table_name="processing_logs")
    op.drop_column("processing_logs", "message")
    op.drop_column("processing_logs", "publication_id")
