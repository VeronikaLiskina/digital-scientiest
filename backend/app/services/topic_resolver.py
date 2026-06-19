from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.topic import Topic
from app.utils.normalization import normalize_topic


async def get_or_create_topic(
    db: AsyncSession,
    name: str,
    description: str | None = None,
) -> Topic:
    normalized_name = normalize_topic(name)

    result = await db.execute(
        select(Topic).where(Topic.normalized_name == normalized_name)
    )
    topic = result.scalar_one_or_none()

    if topic is not None:
        return topic

    topic = Topic(
        name=name.strip(),
        normalized_name=normalized_name,
        description=description.strip() if description else None,
    )
    db.add(topic)
    await db.flush()
    return topic
