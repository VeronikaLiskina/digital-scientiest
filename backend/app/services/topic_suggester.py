from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.topic import Topic
from app.utils.normalization import normalize_topic


async def suggest_topic_names(
    db: AsyncSession,
    *,
    title: str | None,
    keywords: list[str],
) -> list[str]:
    """
    Подбирает темы только из существующего справочника topics.

    Важно: функция НЕ придумывает новые темы из PDF.
    Она нужна, чтобы не плодить мусорные темы при автозаполнении.
    """

    result = await db.execute(select(Topic).order_by(Topic.name))
    topics = list(result.scalars().all())

    haystack = normalize_topic(
        " ".join(
            [
                title or "",
                *keywords,
            ]
        )
    )

    if not haystack:
        return []

    scored: list[tuple[int, str]] = []
    seen: set[str] = set()

    for topic in topics:
        normalized_topic_name = normalize_topic(topic.name)

        if not normalized_topic_name:
            continue

        if normalized_topic_name in haystack and normalized_topic_name not in seen:
            score = 10 + len(normalized_topic_name.split())
            scored.append((score, topic.name))
            seen.add(normalized_topic_name)
            continue

        topic_tokens = {
            token
            for token in normalized_topic_name.split()
            if len(token) >= 5
        }

        if not topic_tokens:
            continue

        matches = sum(1 for token in topic_tokens if token in haystack)

        if matches and normalized_topic_name not in seen:
            scored.append((matches, topic.name))
            seen.add(normalized_topic_name)

    scored.sort(key=lambda item: (-item[0], item[1]))
    return [name for _score, name in scored[:5]]
