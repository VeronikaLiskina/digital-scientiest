from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.database import Base
from app.models.associations import (
    publication_authors,
    publication_keywords,
    publication_topics,
)

if TYPE_CHECKING:
    from app.models.author import Author
    from app.models.document_chunk import DocumentChunk
    from app.models.keyword import Keyword
    from app.models.source_file import SourceFile
    from app.models.topic import Topic


class Publication(Base):
    __tablename__ = "publications"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)

    source_file_id: Mapped[int | None] = mapped_column(
        ForeignKey("source_files.id", ondelete="SET NULL"),
        unique=True,
        nullable=True,
        index=True,
    )

    title: Mapped[str] = mapped_column(String(500), nullable=False)
    year: Mapped[int | None] = mapped_column(Integer, nullable=True)
    language: Mapped[str | None] = mapped_column(String(50), nullable=True)
    publication_type: Mapped[str | None] = mapped_column(String(100), nullable=True)
    doi: Mapped[str | None] = mapped_column(String(255), nullable=True)
    status: Mapped[str] = mapped_column(String(50), default="draft", nullable=False)

    source_file: Mapped["SourceFile | None"] = relationship(
        back_populates="publication",
    )

    authors: Mapped[list["Author"]] = relationship(
        secondary=publication_authors,
        back_populates="publications",
    )

    topics: Mapped[list["Topic"]] = relationship(
        secondary=publication_topics,
        back_populates="publications",
    )

    keywords: Mapped[list["Keyword"]] = relationship(
        secondary=publication_keywords,
        back_populates="publications",
    )

    chunks: Mapped[list["DocumentChunk"]] = relationship(
        back_populates="publication",
        cascade="all, delete-orphan",
    )
