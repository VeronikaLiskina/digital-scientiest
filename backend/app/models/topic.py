from typing import TYPE_CHECKING

from sqlalchemy import String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.database import Base
from app.models.associations import publication_topics

if TYPE_CHECKING:
    from app.models.publication import Publication


class Topic(Base):
    __tablename__ = "topics"

    __table_args__ = (
        UniqueConstraint("normalized_name", name="uq_topics_normalized_name"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, index=True)

    name: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    normalized_name: Mapped[str | None] = mapped_column(
        String(255),
        index=True,
        nullable=True,
    )
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    publications: Mapped[list["Publication"]] = relationship(
        secondary=publication_topics,
        back_populates="topics",
    )
