from typing import TYPE_CHECKING

from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.database import Base
from app.models.associations import publication_keywords

if TYPE_CHECKING:
    from app.models.publication import Publication


class Keyword(Base):
    __tablename__ = "keywords"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)

    name: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)

    publications: Mapped[list["Publication"]] = relationship(
        secondary=publication_keywords,
        back_populates="keywords",
    )