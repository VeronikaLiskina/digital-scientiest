from typing import TYPE_CHECKING

from sqlalchemy import String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.database import Base

if TYPE_CHECKING:
    from app.models.processing_log import ProcessingLog
    from app.models.publication import Publication


class SourceFile(Base):
    __tablename__ = "source_files"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)

    file_name: Mapped[str] = mapped_column(String(255), nullable=False)
    file_path: Mapped[str] = mapped_column(String(500), nullable=False)
    file_type: Mapped[str] = mapped_column(String(50), nullable=False)
    file_hash: Mapped[str | None] = mapped_column(String(64), index=True, nullable=True)

    pdf_quality: Mapped[str | None] = mapped_column(String(100), nullable=True)
    has_figures: Mapped[bool] = mapped_column(default=False)
    has_tables: Mapped[bool] = mapped_column(default=False)

    processing_status: Mapped[str] = mapped_column(
        String(50),
        default="new",
        nullable=False,
    )

    comment: Mapped[str | None] = mapped_column(Text, nullable=True)

    publication: Mapped["Publication | None"] = relationship(
        back_populates="source_file",
    )

    processing_logs: Mapped[list["ProcessingLog"]] = relationship(
        back_populates="source_file",
        cascade="all, delete-orphan",
    )