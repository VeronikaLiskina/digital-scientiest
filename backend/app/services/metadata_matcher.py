from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.author import Author
from app.models.keyword import Keyword
from app.models.topic import Topic
from app.utils.normalization import (
    format_author_display_name,
    normalize_author_identity_key,
    normalize_author_name,
    normalize_keyword,
    normalize_topic,
)


@dataclass
class CatalogMatch:
    id: int
    name: str
    extracted_name: str


@dataclass
class CatalogMatchResult:
    matches: list[CatalogMatch]
    new_names: list[str]


def _dedupe_names(values: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()

    for value in values:
        value = value.strip()
        if not value:
            continue

        key = value.lower().replace("ё", "е")
        if key in seen:
            continue

        seen.add(key)
        result.append(value)

    return result


async def match_existing_authors(
    db: AsyncSession,
    author_names: list[str],
) -> CatalogMatchResult:
    matches: list[CatalogMatch] = []
    new_names: list[str] = []
    seen_match_ids: set[int] = set()

    result = await db.execute(select(Author).order_by(Author.full_name))
    existing_authors = list(result.scalars().all())

    # Индексы строятся в памяти, чтобы preview endpoint ничего не менял в БД.
    by_normalized_name: dict[str, Author] = {}
    by_identity_key: dict[str, Author] = {}

    for author in existing_authors:
        normalized = author.normalized_name or normalize_author_name(author.full_name)
        if normalized and normalized not in by_normalized_name:
            by_normalized_name[normalized] = author

        identity_key = normalize_author_identity_key(author.full_name)
        if identity_key and identity_key not in by_identity_key:
            by_identity_key[identity_key] = author

    for raw_name in _dedupe_names(author_names):
        canonical_name = format_author_display_name(raw_name)

        # Если парсер не смог привести к Фамилия И.О., не автосвязываем и не предлагаем создавать.
        # Пользователь всё равно может вручную добавить автора в форме.
        if canonical_name is None:
            continue

        normalized = normalize_author_name(canonical_name)
        identity_key = normalize_author_identity_key(canonical_name)

        author = by_normalized_name.get(normalized)
        if author is None and identity_key:
            author = by_identity_key.get(identity_key)

        if author is not None:
            if author.id in seen_match_ids:
                continue

            seen_match_ids.add(author.id)
            matches.append(
                CatalogMatch(
                    id=author.id,
                    name=author.full_name,
                    extracted_name=canonical_name,
                )
            )
            continue

        new_names.append(canonical_name)

    return CatalogMatchResult(matches=matches, new_names=_dedupe_names(new_names))


async def match_existing_keywords(
    db: AsyncSession,
    keyword_names: list[str],
) -> CatalogMatchResult:
    result = await db.execute(select(Keyword).order_by(Keyword.name))
    existing_keywords = list(result.scalars().all())

    by_normalized_name = {
        keyword.normalized_name or normalize_keyword(keyword.name): keyword
        for keyword in existing_keywords
    }

    matches: list[CatalogMatch] = []
    new_names: list[str] = []
    seen_match_ids: set[int] = set()

    for name in _dedupe_names(keyword_names):
        normalized = normalize_keyword(name)
        keyword = by_normalized_name.get(normalized)

        if keyword is not None:
            if keyword.id in seen_match_ids:
                continue

            seen_match_ids.add(keyword.id)
            matches.append(
                CatalogMatch(
                    id=keyword.id,
                    name=keyword.name,
                    extracted_name=name,
                )
            )
            continue

        new_names.append(name)

    return CatalogMatchResult(matches=matches, new_names=_dedupe_names(new_names))


async def match_existing_topics(
    db: AsyncSession,
    topic_names: list[str],
) -> CatalogMatchResult:
    result = await db.execute(select(Topic).order_by(Topic.name))
    existing_topics = list(result.scalars().all())

    by_normalized_name = {
        topic.normalized_name or normalize_topic(topic.name): topic
        for topic in existing_topics
    }

    matches: list[CatalogMatch] = []
    new_names: list[str] = []
    seen_match_ids: set[int] = set()

    for name in _dedupe_names(topic_names):
        normalized = normalize_topic(name)
        topic = by_normalized_name.get(normalized)

        if topic is not None:
            if topic.id in seen_match_ids:
                continue

            seen_match_ids.add(topic.id)
            matches.append(
                CatalogMatch(
                    id=topic.id,
                    name=topic.name,
                    extracted_name=name,
                )
            )
            continue

        new_names.append(name)

    return CatalogMatchResult(matches=matches, new_names=_dedupe_names(new_names))
