import asyncio

from sqlalchemy import select

from app.db.database import async_session_maker
from app.models.author import Author
from app.models.keyword import Keyword
from app.models.topic import Topic
from app.utils.normalization import (
    normalize_author_name,
    normalize_keyword,
    normalize_topic,
)


async def main() -> None:
    async with async_session_maker() as db:
        authors = await db.execute(select(Author))
        for author in authors.scalars().all():
            author.normalized_name = normalize_author_name(author.full_name)

        keywords = await db.execute(select(Keyword))
        for keyword in keywords.scalars().all():
            keyword.normalized_name = normalize_keyword(keyword.name)

        topics = await db.execute(select(Topic))
        for topic in topics.scalars().all():
            topic.normalized_name = normalize_topic(topic.name)

        await db.commit()


if __name__ == "__main__":
    asyncio.run(main())
