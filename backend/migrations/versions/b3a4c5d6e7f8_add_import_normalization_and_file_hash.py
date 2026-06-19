"""add import normalization and file hash

Revision ID: b3a4c5d6e7f8
Revises: 55ec1c9c1372
Create Date: 2026-06-18 16:20:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "b3a4c5d6e7f8"
down_revision: Union[str, Sequence[str], None] = "55ec1c9c1372"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "authors",
        sa.Column("normalized_name", sa.String(length=255), nullable=True),
    )
    op.create_index(
        op.f("ix_authors_normalized_name"),
        "authors",
        ["normalized_name"],
        unique=False,
    )

    op.add_column(
        "keywords",
        sa.Column("normalized_name", sa.String(length=255), nullable=True),
    )
    op.create_index(
        op.f("ix_keywords_normalized_name"),
        "keywords",
        ["normalized_name"],
        unique=False,
    )

    op.add_column(
        "topics",
        sa.Column("normalized_name", sa.String(length=255), nullable=True),
    )
    op.create_index(
        op.f("ix_topics_normalized_name"),
        "topics",
        ["normalized_name"],
        unique=False,
    )

    op.add_column(
        "source_files",
        sa.Column("file_hash", sa.String(length=64), nullable=True),
    )
    op.create_index(
        op.f("ix_source_files_file_hash"),
        "source_files",
        ["file_hash"],
        unique=False,
    )

    # Заполняем normalized_name для уже существующих записей.
    # Если после этого в БД есть дубли, создание unique-ограничений ниже упадет.
    # Тогда нужно объединить дубли и повторить alembic upgrade head.
    op.execute(
        """
        UPDATE authors
        SET normalized_name = regexp_replace(
            lower(trim(replace(full_name, 'ё', 'е'))),
            '\\s+',
            ' ',
            'g'
        )
        WHERE normalized_name IS NULL
        """
    )
    op.execute(
        """
        UPDATE keywords
        SET normalized_name = regexp_replace(
            lower(trim(replace(name, 'ё', 'е'))),
            '\\s+',
            ' ',
            'g'
        )
        WHERE normalized_name IS NULL
        """
    )
    op.execute(
        """
        UPDATE topics
        SET normalized_name = regexp_replace(
            lower(trim(replace(name, 'ё', 'е'))),
            '\\s+',
            ' ',
            'g'
        )
        WHERE normalized_name IS NULL
        """
    )

    op.create_unique_constraint(
        "uq_authors_normalized_name",
        "authors",
        ["normalized_name"],
    )
    op.create_unique_constraint(
        "uq_keywords_normalized_name",
        "keywords",
        ["normalized_name"],
    )
    op.create_unique_constraint(
        "uq_topics_normalized_name",
        "topics",
        ["normalized_name"],
    )


def downgrade() -> None:
    op.drop_constraint("uq_topics_normalized_name", "topics", type_="unique")
    op.drop_constraint("uq_keywords_normalized_name", "keywords", type_="unique")
    op.drop_constraint("uq_authors_normalized_name", "authors", type_="unique")

    op.drop_index(op.f("ix_source_files_file_hash"), table_name="source_files")
    op.drop_column("source_files", "file_hash")

    op.drop_index(op.f("ix_topics_normalized_name"), table_name="topics")
    op.drop_column("topics", "normalized_name")

    op.drop_index(op.f("ix_keywords_normalized_name"), table_name="keywords")
    op.drop_column("keywords", "normalized_name")

    op.drop_index(op.f("ix_authors_normalized_name"), table_name="authors")
    op.drop_column("authors", "normalized_name")
