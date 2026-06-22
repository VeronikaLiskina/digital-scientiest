from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.author import Author
from app.utils.normalization import (
    format_author_display_name,
    normalize_author_identity_key,
    normalize_author_name,
)


async def find_author_by_identity(
    db: AsyncSession,
    full_name: str,
) -> Author | None:
    """
    Ищет автора не только по точному normalized_name, но и по мягкому ключу ФИО.

    Это нужно, чтобы не создавать дубль, если в БД уже есть:
    - Иванов А.В.

    а из PDF/формы пришло:
    - Иванов Алексей В.
    - Иванов Алексей Викторович
    - Иванов А. В.
    """

    normalized_name = normalize_author_name(full_name)

    exact_result = await db.execute(
        select(Author).where(Author.normalized_name == normalized_name)
    )
    exact_author = exact_result.scalar_one_or_none()

    if exact_author is not None:
        return exact_author

    identity_key = normalize_author_identity_key(full_name)

    if identity_key is None:
        return None

    result = await db.execute(select(Author))
    authors = result.scalars().all()

    for author in authors:
        existing_key = normalize_author_identity_key(author.full_name)

        if existing_key == identity_key:
            canonical_name = format_author_display_name(author.full_name)

            if canonical_name and author.full_name != canonical_name:
                author.full_name = canonical_name

            if not author.normalized_name or canonical_name:
                author.normalized_name = normalize_author_name(author.full_name)

            return author

    return None


async def get_or_create_author(
    db: AsyncSession,
    full_name: str,
    organization: str | None = None,
) -> Author:
    display_name = format_author_display_name(full_name) or full_name.strip()
    existing_author = await find_author_by_identity(db, display_name)

    if existing_author is not None:
        return existing_author

    author = Author(
        full_name=display_name,
        normalized_name=normalize_author_name(display_name),
        organization=organization.strip() if organization else None,
    )
    db.add(author)
    await db.flush()
    return author
