from sqlalchemy import Column, ForeignKey, Table

from app.db.database import Base


publication_authors = Table(
    "publication_authors",
    Base.metadata,
    Column(
        "publication_id",
        ForeignKey("publications.id", ondelete="CASCADE"),
        primary_key=True,
    ),
    Column(
        "author_id",
        ForeignKey("authors.id", ondelete="CASCADE"),
        primary_key=True,
    ),
)


publication_topics = Table(
    "publication_topics",
    Base.metadata,
    Column(
        "publication_id",
        ForeignKey("publications.id", ondelete="CASCADE"),
        primary_key=True,
    ),
    Column(
        "topic_id",
        ForeignKey("topics.id", ondelete="CASCADE"),
        primary_key=True,
    ),
)


publication_keywords = Table(
    "publication_keywords",
    Base.metadata,
    Column(
        "publication_id",
        ForeignKey("publications.id", ondelete="CASCADE"),
        primary_key=True,
    ),
    Column(
        "keyword_id",
        ForeignKey("keywords.id", ondelete="CASCADE"),
        primary_key=True,
    ),
)