import asyncio
import math

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.topic import Topic
from app.utils.normalization import normalize_topic


def _cosine_similarity(left: list[float], right: list[float]) -> float:
    if not left or not right:
        return 0.0

    dot = sum(a * b for a, b in zip(left, right))
    left_norm = math.sqrt(sum(a * a for a in left))
    right_norm = math.sqrt(sum(b * b for b in right))

    if left_norm == 0.0 or right_norm == 0.0:
        return 0.0

    return dot / (left_norm * right_norm)


async def suggest_topic_names(
    db: AsyncSession,
    *,
    title: str | None,
    keywords: list[str],
    embedding_service=None,
) -> list[str]:
    """
    Подбирает темы только из существующего справочника topics.

    Важно: функция НЕ придумывает новые темы из PDF.
    Она нужна, чтобы не плодить мусорные темы при автозаполнении.
    """

    result = await db.execute(select(Topic).order_by(Topic.name))
    topics = list(result.scalars().all())

    query_text = " ".join(
        [
            title or "",
            *keywords,
        ]
    ).strip()
    haystack = normalize_topic(query_text)

    if not haystack:
        return []

    scored: list[tuple[float, str]] = []
    seen: set[str] = set()
    topic_candidates: list[tuple[str, str]] = []

    for topic in topics:
        normalized_topic_name = normalize_topic(topic.name)

        if not normalized_topic_name:
            continue

        topic_candidates.append((topic.name, normalized_topic_name))

    topic_embeddings: list[list[float]] = []
    query_embedding: list[float] | None = None

    if embedding_service is not None:
        query_embedding = await asyncio.to_thread(
            embedding_service.embed_query,
            query_text,
        )
        topic_texts = [name for _name, name in topic_candidates]
        topic_embeddings = await asyncio.to_thread(
            embedding_service.embed_documents,
            topic_texts,
        )

    for index, (topic_name, normalized_topic_name) in enumerate(topic_candidates):
        if normalized_topic_name in haystack and normalized_topic_name not in seen:
            score = 10 + len(normalized_topic_name.split())
            scored.append((score, topic_name))
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
        embedding_score = 0.0

        if embedding_service is not None and query_embedding is not None:
            similarity = 0.0
            if index < len(topic_embeddings):
                similarity = _cosine_similarity(
                    query_embedding,
                    topic_embeddings[index],
                )

            if similarity > 0.35:
                embedding_score = similarity * 4.0

        if matches or embedding_score > 0:
            score = matches + embedding_score
            if normalized_topic_name not in seen:
                scored.append((score, topic_name))
                seen.add(normalized_topic_name)

    scored.sort(key=lambda item: (-item[0], item[1]))
    return [name for _score, name in scored[:5]]
