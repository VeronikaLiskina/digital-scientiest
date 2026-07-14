from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import delete, exists, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.associations import (
    publication_authors,
    publication_keywords,
    publication_topics,
)
from app.models.author import Author
from app.models.keyword import Keyword
from app.models.publication import Publication
from app.models.source_file import SourceFile
from app.models.topic import Topic


@dataclass(frozen=True, slots=True)
class PublicationCleanupResult:
    source_file_id: int | None
    source_file_path: str | None


def _managed_upload_path(file_path: str | None) -> Path | None:
    """Resolve a stored path only when it stays inside the upload directory."""

    if not file_path:
        return None

    upload_root = Path(settings.upload_dir).resolve()
    normalized_path = Path(file_path.replace("\\", "/"))
    candidate = (
        normalized_path.resolve()
        if normalized_path.is_absolute()
        else (Path.cwd() / normalized_path).resolve()
    )

    try:
        candidate.relative_to(upload_root)
    except ValueError:
        return None

    if candidate == upload_root:
        return None

    return candidate


def delete_managed_upload_file(file_path: str | None) -> bool:
    """Delete a regular file under uploads without following external paths."""

    managed_path = _managed_upload_path(file_path)

    if managed_path is None or not managed_path.is_file():
        return False

    managed_path.unlink()
    return True


async def _delete_unused_catalog_entries(
    db: AsyncSession,
    *,
    author_ids: list[int],
    topic_ids: list[int],
    keyword_ids: list[int],
) -> None:
    if author_ids:
        await db.execute(
            delete(Author)
            .where(Author.id.in_(author_ids))
            .where(
                ~exists(
                    select(publication_authors.c.author_id).where(
                        publication_authors.c.author_id == Author.id
                    )
                )
            )
            .execution_options(synchronize_session=False)
        )

    if topic_ids:
        await db.execute(
            delete(Topic)
            .where(Topic.id.in_(topic_ids))
            .where(
                ~exists(
                    select(publication_topics.c.topic_id).where(
                        publication_topics.c.topic_id == Topic.id
                    )
                )
            )
            .execution_options(synchronize_session=False)
        )

    if keyword_ids:
        await db.execute(
            delete(Keyword)
            .where(Keyword.id.in_(keyword_ids))
            .where(
                ~exists(
                    select(publication_keywords.c.keyword_id).where(
                        publication_keywords.c.keyword_id == Keyword.id
                    )
                )
            )
            .execution_options(synchronize_session=False)
        )


async def delete_publication_with_resources(
    db: AsyncSession,
    publication: Publication,
) -> PublicationCleanupResult:
    """Delete a publication and resources that are no longer used elsewhere."""

    author_ids = [author.id for author in publication.authors]
    topic_ids = [topic.id for topic in publication.topics]
    keyword_ids = [keyword.id for keyword in publication.keywords]
    source_file_id = publication.source_file_id
    source_file = (
        await db.get(SourceFile, source_file_id)
        if source_file_id is not None
        else None
    )
    source_file_path = source_file.file_path if source_file is not None else None

    await db.delete(publication)
    await db.flush()

    await _delete_unused_catalog_entries(
        db,
        author_ids=author_ids,
        topic_ids=topic_ids,
        keyword_ids=keyword_ids,
    )

    if source_file_id is not None:
        await db.execute(
            delete(SourceFile)
            .where(SourceFile.id == source_file_id)
            .where(
                ~exists(
                    select(Publication.id).where(
                        Publication.source_file_id == SourceFile.id
                    )
                )
            )
            .execution_options(synchronize_session=False)
        )

    await db.commit()

    return PublicationCleanupResult(
        source_file_id=source_file_id,
        source_file_path=source_file_path,
    )
