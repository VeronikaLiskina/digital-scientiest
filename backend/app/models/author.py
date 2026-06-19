from typing import TYPE_CHECKING

from sqlalchemy import String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.database import Base
from app.models.associations import publication_authors

if TYPE_CHECKING:
    from app.models.publication import Publication


class Author(Base):
    __tablename__ = "authors"

    __table_args__ = (
        UniqueConstraint("full_name", "organization", name="uq_author_name_org"),
        UniqueConstraint("normalized_name", name="uq_authors_normalized_name"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, index=True)

    full_name: Mapped[str] = mapped_column(String(255), nullable=False)
    normalized_name: Mapped[str | None] = mapped_column(
        String(255),
        index=True,
        nullable=True,
    )
    organization: Mapped[str | None] = mapped_column(String(255), nullable=True)

    publications: Mapped[list["Publication"]] = relationship(
        secondary=publication_authors,
        back_populates="authors",
    )
