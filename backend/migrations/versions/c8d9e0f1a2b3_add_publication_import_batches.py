"""add publication import batches

Revision ID: c8d9e0f1a2b3
Revises: b3a4c5d6e7f8
Create Date: 2026-06-25 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "c8d9e0f1a2b3"
down_revision: Union[str, Sequence[str], None] = "b3a4c5d6e7f8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "import_batches",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=50), nullable=False),
        sa.Column("total_files", sa.Integer(), nullable=False),
        sa.Column("processed_count", sa.Integer(), nullable=False),
        sa.Column("needs_review_count", sa.Integer(), nullable=False),
        sa.Column("saved_count", sa.Integer(), nullable=False),
        sa.Column("duplicate_count", sa.Integer(), nullable=False),
        sa.Column("error_count", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_import_batches_id"), "import_batches", ["id"], unique=False)

    op.create_table(
        "import_items",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("batch_id", sa.Integer(), nullable=False),
        sa.Column("source_file_id", sa.Integer(), nullable=True),
        sa.Column("publication_id", sa.Integer(), nullable=True),
        sa.Column("original_file_name", sa.String(length=255), nullable=False),
        sa.Column("status", sa.String(length=50), nullable=False),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("extracted_metadata_json", sa.JSON(), nullable=True),
        sa.Column("title", sa.String(length=500), nullable=True),
        sa.Column("title_source", sa.String(length=50), nullable=True),
        sa.Column("title_confidence", sa.String(length=50), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["batch_id"], ["import_batches.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["publication_id"], ["publications.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["source_file_id"], ["source_files.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_import_items_batch_id"), "import_items", ["batch_id"], unique=False)
    op.create_index(op.f("ix_import_items_id"), "import_items", ["id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_import_items_id"), table_name="import_items")
    op.drop_index(op.f("ix_import_items_batch_id"), table_name="import_items")
    op.drop_table("import_items")
    op.drop_index(op.f("ix_import_batches_id"), table_name="import_batches")
    op.drop_table("import_batches")
