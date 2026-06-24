from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import DateTime, ForeignKey, Integer, JSON, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.database import Base

if TYPE_CHECKING:
    from app.models.publication import Publication
    from app.models.source_file import SourceFile


class ImportBatch(Base):
    __tablename__ = "import_batches"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    status: Mapped[str] = mapped_column(String(50), default="processing", nullable=False)

    total_files: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    processed_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    needs_review_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    saved_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    duplicate_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    error_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    items: Mapped[list["ImportItem"]] = relationship(
        back_populates="batch",
        cascade="all, delete-orphan",
    )


class ImportItem(Base):
    __tablename__ = "import_items"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    batch_id: Mapped[int] = mapped_column(
        ForeignKey("import_batches.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    source_file_id: Mapped[int | None] = mapped_column(
        ForeignKey("source_files.id", ondelete="SET NULL"),
        nullable=True,
    )
    publication_id: Mapped[int | None] = mapped_column(
        ForeignKey("publications.id", ondelete="SET NULL"),
        nullable=True,
    )

    original_file_name: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(String(50), default="processing", nullable=False)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    extracted_metadata_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    title: Mapped[str | None] = mapped_column(String(500), nullable=True)
    title_source: Mapped[str | None] = mapped_column(String(50), nullable=True)
    title_confidence: Mapped[str | None] = mapped_column(String(50), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    batch: Mapped["ImportBatch"] = relationship(back_populates="items")
    source_file: Mapped["SourceFile | None"] = relationship()
    publication: Mapped["Publication | None"] = relationship()
