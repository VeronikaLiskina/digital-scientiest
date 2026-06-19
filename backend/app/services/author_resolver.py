from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.author import Author
from app.utils.normalization import normalize_author_name


async def get_or_create_author(
    db: AsyncSession,
    full_name: str,
    organization: str | None = None,
) -> Author:
    normalized_name = normalize_author_name(full_name)

    result = await db.execute(
        select(Author).where(Author.normalized_name == normalized_name)
    )
    author = result.scalar_one_or_none()

    if author is not None:
        return author

    author = Author(
        full_name=full_name.strip(),
        normalized_name=normalized_name,
        organization=organization.strip() if organization else None,
    )
    db.add(author)
    await db.flush()
    return author
