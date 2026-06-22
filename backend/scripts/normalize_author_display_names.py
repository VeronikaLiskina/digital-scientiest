import asyncio

from sqlalchemy import select

from app.db.database import async_session_maker
from app.models.author import Author
from app.utils.normalization import format_author_display_name, normalize_author_name


async def main() -> None:
    async with async_session_maker() as session:
        result = await session.execute(select(Author))
        authors = result.scalars().all()

        changed = 0

        for author in authors:
            display_name = format_author_display_name(author.full_name)

            if not display_name:
                continue

            normalized_name = normalize_author_name(display_name)

            if author.full_name != display_name or author.normalized_name != normalized_name:
                author.full_name = display_name
                author.normalized_name = normalized_name
                changed += 1

        await session.commit()

    print(f"Updated authors: {changed}")


if __name__ == "__main__":
    asyncio.run(main())
