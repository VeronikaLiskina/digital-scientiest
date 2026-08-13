"""add structured assistant answers

Revision ID: b4c5d6e7f8a9
Revises: a3b4c5d6e7f8
Create Date: 2026-07-21 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "b4c5d6e7f8a9"
down_revision: Union[str, Sequence[str], None] = "a3b4c5d6e7f8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "chat_messages",
        sa.Column("answer_origin", sa.String(length=30), nullable=True),
    )
    op.add_column(
        "chat_messages",
        sa.Column("answer_blocks", sa.JSON(), nullable=True),
    )
    op.execute(
        """
        UPDATE chat_messages
        SET answer_origin = CASE response_kind
            WHEN 'rag' THEN 'internal'
            WHEN 'general_knowledge' THEN 'external'
            WHEN 'database' THEN CASE
                WHEN catalog IS NULL THEN 'internal'
                ELSE 'catalog'
            END
            ELSE NULL
        END
        WHERE answer_origin IS NULL
        """
    )


def downgrade() -> None:
    op.drop_column("chat_messages", "answer_blocks")
    op.drop_column("chat_messages", "answer_origin")
