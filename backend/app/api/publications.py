from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db.database import get_db
from app.models.author import Author
from app.models.keyword import Keyword
from app.models.publication import Publication
from app.models.source_file import SourceFile
from app.models.topic import Topic
from app.schemas.publication import PublicationCreate, PublicationRead, PublicationUpdate


router = APIRouter(prefix="/publications", tags=["Publications"])


def publication_load_options():
    return (
        selectinload(Publication.authors),
        selectinload(Publication.topics),
        selectinload(Publication.keywords),
    )


async def get_publication_or_404(
    publication_id: int,
    db: AsyncSession,
) -> Publication:
    result = await db.execute(
        select(Publication)
        .where(Publication.id == publication_id)
        .options(*publication_load_options())
    )

    publication = result.scalar_one_or_none()

    if publication is None:
        raise HTTPException(status_code=404, detail="Publication not found")

    return publication


async def get_items_by_ids(
    db: AsyncSession,
    model,
    ids: list[int],
):
    if not ids:
        return []

    result = await db.execute(select(model).where(model.id.in_(ids)))
    items = list(result.scalars().all())

    if len(items) != len(set(ids)):
        raise HTTPException(
            status_code=400,
            detail=f"Some {model.__tablename__} ids do not exist",
        )

    return items


async def check_source_file_exists(
    db: AsyncSession,
    source_file_id: int | None,
):
    if source_file_id is None:
        return

    source_file = await db.get(SourceFile, source_file_id)

    if source_file is None:
        raise HTTPException(status_code=400, detail="Source file not found")


@router.post("", response_model=PublicationRead, status_code=status.HTTP_201_CREATED)
async def create_publication(
    data: PublicationCreate,
    db: AsyncSession = Depends(get_db),
):
    await check_source_file_exists(db, data.source_file_id)

    publication = Publication(
        title=data.title,
        year=data.year,
        language=data.language,
        publication_type=data.publication_type,
        doi=data.doi,
        status=data.status,
        source_file_id=data.source_file_id,
    )

    publication.authors = await get_items_by_ids(db, Author, data.author_ids)
    publication.topics = await get_items_by_ids(db, Topic, data.topic_ids)
    publication.keywords = await get_items_by_ids(db, Keyword, data.keyword_ids)

    db.add(publication)
    await db.commit()

    return await get_publication_or_404(publication.id, db)


@router.get("", response_model=list[PublicationRead])
async def get_publications(
    title: str | None = Query(default=None),
    year: int | None = Query(default=None),
    author_id: int | None = Query(default=None),
    topic_id: int | None = Query(default=None),
    keyword_id: int | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
):
    query = (
        select(Publication)
        .options(*publication_load_options())
        .order_by(Publication.id.desc())
    )

    if title:
        query = query.where(Publication.title.ilike(f"%{title}%"))

    if year:
        query = query.where(Publication.year == year)

    if author_id:
        query = query.where(Publication.authors.any(Author.id == author_id))

    if topic_id:
        query = query.where(Publication.topics.any(Topic.id == topic_id))

    if keyword_id:
        query = query.where(Publication.keywords.any(Keyword.id == keyword_id))

    result = await db.execute(query)
    return result.scalars().all()


@router.get("/{publication_id}", response_model=PublicationRead)
async def get_publication(
    publication_id: int,
    db: AsyncSession = Depends(get_db),
):
    return await get_publication_or_404(publication_id, db)


@router.patch("/{publication_id}", response_model=PublicationRead)
async def update_publication(
    publication_id: int,
    data: PublicationUpdate,
    db: AsyncSession = Depends(get_db),
):
    publication = await get_publication_or_404(publication_id, db)

    update_data = data.model_dump(
        exclude_unset=True,
        exclude={"author_ids", "topic_ids", "keyword_ids"},
    )

    if "source_file_id" in update_data:
        await check_source_file_exists(db, update_data["source_file_id"])

    for field, value in update_data.items():
        setattr(publication, field, value)

    if data.author_ids is not None:
        publication.authors = await get_items_by_ids(db, Author, data.author_ids)

    if data.topic_ids is not None:
        publication.topics = await get_items_by_ids(db, Topic, data.topic_ids)

    if data.keyword_ids is not None:
        publication.keywords = await get_items_by_ids(db, Keyword, data.keyword_ids)

    await db.commit()

    return await get_publication_or_404(publication.id, db)


@router.delete("/{publication_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_publication(
    publication_id: int,
    db: AsyncSession = Depends(get_db),
):
    publication = await get_publication_or_404(publication_id, db)

    await db.delete(publication)
    await db.commit()