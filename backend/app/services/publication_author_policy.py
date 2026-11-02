"""The catalogue owner is linked independently of PDF author recognition."""
from sqlalchemy import literal, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.database import async_session_maker
from app.models.associations import publication_authors
from app.models.author import Author
from app.models.publication import Publication
from app.utils.normalization import author_identity_signature, normalize_author_name


REQUIRED_AUTHOR_NAME = "Иванов А.В."


def is_required_author(name: str) -> bool:
    return author_identity_signature(name) == author_identity_signature(REQUIRED_AUTHOR_NAME)


async def with_required_author(db: AsyncSession, authors: list[Author]) -> list[Author]:
    if any(is_required_author(author.full_name) for author in authors):
        return authors
    required = await _get_required_author(db)
    return [*authors, required]


async def _get_required_author(db: AsyncSession) -> Author:
    authors = (await db.scalars(select(Author).order_by(Author.id))).all()
    existing = next((author for author in authors if is_required_author(author.full_name)), None)
    if existing is not None:
        return existing
    normalized = normalize_author_name(REQUIRED_AUTHOR_NAME)
    await db.execute(insert(Author).values(
        full_name=REQUIRED_AUTHOR_NAME, normalized_name=normalized,
    ).on_conflict_do_nothing(index_elements=[Author.normalized_name]))
    return (await db.scalars(select(Author).where(Author.normalized_name == normalized))).one()


async def synchronize_required_publication_authors() -> int:
    async with async_session_maker() as db:
        if await db.scalar(select(Publication.id).limit(1)) is None:
            return 0
        required = await _get_required_author(db)
        missing = select(Publication.id, literal(required.id)).where(
            ~Publication.authors.any(Author.id == required.id),
        )
        result = await db.execute(insert(publication_authors).from_select(
            ["publication_id", "author_id"], missing,
        ).on_conflict_do_nothing())
        await db.commit()
        return result.rowcount
