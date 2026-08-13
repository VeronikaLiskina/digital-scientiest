"""add celery PDF task tracking

Revision ID: c5d6e7f8a9b0
Revises: b4c5d6e7f8a9
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "c5d6e7f8a9b0"
down_revision: Union[str, Sequence[str], None] = "b4c5d6e7f8a9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "source_files",
        sa.Column("processing_task_id", sa.String(length=255), nullable=True),
    )
    op.create_index(
        op.f("ix_source_files_processing_task_id"),
        "source_files",
        ["processing_task_id"],
        unique=False,
    )
    op.execute(
        "UPDATE source_files SET processing_status = 'completed' "
        "WHERE processing_status = 'processed'"
    )
    op.execute(
        "UPDATE source_files SET processing_status = 'failed' "
        "WHERE processing_status = 'error'"
    )


def downgrade() -> None:
    op.execute(
        "UPDATE source_files SET processing_status = 'processed' "
        "WHERE processing_status = 'completed'"
    )
    op.execute(
        "UPDATE source_files SET processing_status = 'error' "
        "WHERE processing_status = 'failed'"
    )
    op.drop_index(
        op.f("ix_source_files_processing_task_id"),
        table_name="source_files",
    )
    op.drop_column("source_files", "processing_task_id")
