import json
import re
from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db.database import get_db
from app.models.author import Author
from app.models.keyword import Keyword
from app.models.publication import Publication
from app.models.publication_import import ImportBatch, ImportItem
from app.models.source_file import SourceFile
from app.models.topic import Topic
from app.schemas.publication import PublicationCreate, PublicationRead, PublicationUpdate
from app.services.pdf_import import save_uploaded_pdf_as_source_file
from app.services.pdf_processing_queue import enqueue_pdf_processing
from app.services.publication_cleanup_service import (
    delete_managed_upload_file,
    delete_publication_with_resources,
)
from app.services.author_resolver import get_or_create_author
from app.services.keyword_resolver import get_or_create_keyword
from app.services.topic_resolver import get_or_create_topic


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

    unique_ids = list(set(ids))

    result = await db.execute(
        select(model).where(model.id.in_(unique_ids))
    )
    items = list(result.scalars().all())

    if len(items) != len(unique_ids):
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


def parse_ids(value: str | None) -> list[int]:
    """
    Для multipart/form-data.

    Поддерживает два варианта:
    "1,2,3"
    или
    "[1, 2, 3]"
    """

    if not value:
        return []

    value = value.strip()

    if not value:
        return []

    try:
        if value.startswith("["):
            parsed = json.loads(value)

            if not isinstance(parsed, list):
                raise ValueError

            return [int(item) for item in parsed]

        return [
            int(item.strip())
            for item in value.split(",")
            if item.strip()
        ]

    except (ValueError, TypeError, json.JSONDecodeError):
        raise HTTPException(
            status_code=400,
            detail=f"Некорректный список id: {value}",
        )


def parse_names(value: str | None) -> list[str]:
    """
    Для имен, пришедших из автозаполненных полей формы.

    Поддерживает ввод через точку с запятой, переносы строк и запятые.
    Эти значения НЕ создаются при выборе PDF. Они создаются/находятся
    только при финальном сохранении публикации.
    """

    if not value:
        return []

    names: list[str] = []
    seen: set[str] = set()

    for item in re.split(r";|,|\n", value):
        name = item.strip()

        if not name:
            continue

        normalized = name.lower().replace("ё", "е")

        if normalized in seen:
            continue

        seen.add(normalized)
        names.append(name)

    return names


def dedupe_by_id(items):
    result = []
    seen_ids = set()

    for item in items:
        item_id = getattr(item, "id", None)

        if item_id in seen_ids:
            continue

        seen_ids.add(item_id)
        result.append(item)

    return result


async def resolve_authors(
    db: AsyncSession,
    *,
    ids: list[int],
    names: list[str],
) -> list[Author]:
    authors = await get_items_by_ids(db, Author, ids)

    for name in names:
        authors.append(await get_or_create_author(db, name))

    return dedupe_by_id(authors)


async def resolve_topics(
    db: AsyncSession,
    *,
    ids: list[int],
    names: list[str],
) -> list[Topic]:
    topics = await get_items_by_ids(db, Topic, ids)

    for name in names:
        topics.append(await get_or_create_topic(db, name))

    return dedupe_by_id(topics)


async def resolve_keywords(
    db: AsyncSession,
    *,
    ids: list[int],
    names: list[str],
) -> list[Keyword]:
    keywords = await get_items_by_ids(db, Keyword, ids)

    for name in names:
        keywords.append(await get_or_create_keyword(db, name))

    return dedupe_by_id(keywords)


def normalize_publication_type(value: str) -> str:
    """
    Чтобы backend нормально принимал и английские значения,
    и русские значения из интерфейса.
    """

    publication_type_map = {
        "article": "article",
        "статья": "article",

        "conference": "conference",
        "материалы конференции": "conference",
        "конференция": "conference",

        "report": "report",
        "отчет": "report",
        "отчёт": "report",

        "book": "book",
        "книга": "book",

        "thesis": "thesis",
        "abstract": "thesis",
        "тезисы": "thesis",
    }

    normalized = publication_type_map.get(value.strip().lower())

    if normalized is None:
        raise HTTPException(
            status_code=400,
            detail=f"Некорректный тип публикации: {value}",
        )

    return normalized


def normalize_language(value: str) -> str:
    language_map = {
        "ru": "ru",
        "rus": "ru",
        "russian": "ru",
        "русский": "ru",

        "en": "en",
        "eng": "en",
        "english": "en",
        "английский": "en",
    }

    normalized = language_map.get(value.strip().lower())

    if normalized is None:
        return value

    return normalized


async def save_uploaded_pdf(file: UploadFile, db: AsyncSession) -> SourceFile:
    source_file, _ = await save_uploaded_pdf_as_source_file(
        db=db,
        file=file,
        comment="Файл загружен при создании публикации",
        fail_on_duplicate=True,
    )
    return source_file


def recalculate_import_batch(batch: ImportBatch) -> None:
    items = list(batch.items)
    batch.total_files = len(items)
    batch.processed_count = len(
        [item for item in items if item.status != "processing"]
    )
    batch.needs_review_count = len(
        [item for item in items if item.status == "needs_review"]
    )
    batch.saved_count = len([item for item in items if item.status == "saved"])
    batch.duplicate_count = len(
        [item for item in items if item.status == "duplicate"]
    )
    batch.error_count = len([item for item in items if item.status == "error"])

    if batch.error_count and not batch.needs_review_count:
        batch.status = "completed_with_errors"
    elif batch.needs_review_count:
        batch.status = "needs_review"
    else:
        batch.status = "completed"


async def mark_import_item_saved(
    db: AsyncSession,
    *,
    import_item_id: int | None,
    publication: Publication,
) -> None:
    if import_item_id is None:
        return

    result = await db.execute(
        select(ImportItem)
        .where(ImportItem.id == import_item_id)
        .options(selectinload(ImportItem.batch).selectinload(ImportBatch.items))
    )
    item = result.scalar_one_or_none()

    if item is None:
        raise HTTPException(status_code=404, detail="Import item not found")

    if item.status != "needs_review":
        raise HTTPException(
            status_code=400,
            detail="Import item is not ready for review",
        )

    if item.source_file_id and publication.source_file_id != item.source_file_id:
        raise HTTPException(
            status_code=400,
            detail="Publication source file does not match import item",
        )

    item.publication_id = publication.id
    item.status = "saved"
    item.error_message = None
    recalculate_import_batch(item.batch)


@router.post("", response_model=PublicationRead, status_code=status.HTTP_201_CREATED)
async def create_publication(
    data: PublicationCreate,
    db: AsyncSession = Depends(get_db),
):
    source_file_id = data.source_file_id

    if data.import_item_id is not None and source_file_id is None:
        import_item = await db.get(ImportItem, data.import_item_id)
        if import_item is None:
            raise HTTPException(status_code=404, detail="Import item not found")
        source_file_id = import_item.source_file_id

    await check_source_file_exists(db, source_file_id)

    authors = await resolve_authors(
        db,
        ids=data.author_ids,
        names=data.author_names,
    )
    topics = await resolve_topics(
        db,
        ids=data.topic_ids,
        names=data.topic_names,
    )
    keywords = await resolve_keywords(
        db,
        ids=data.keyword_ids,
        names=data.keyword_names,
    )

    publication = Publication(
        title=data.title,
        year=data.year,
        language=data.language,
        publication_type=data.publication_type,
        doi=data.doi,
        status=data.status,
        source_file_id=source_file_id,
    )

    publication.authors = authors
    publication.topics = topics
    publication.keywords = keywords

    db.add(publication)
    await db.flush()

    await mark_import_item_saved(
        db,
        import_item_id=data.import_item_id,
        publication=publication,
    )

    await db.commit()

    if data.import_item_id is not None and source_file_id is not None:
        await enqueue_pdf_processing(
            db,
            source_file_id,
            skip_processed=True,
        )

    return await get_publication_or_404(publication.id, db)


@router.post(
    "/with-file",
    response_model=PublicationRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_publication_with_file(
    title: str = Form(...),
    year: int | None = Form(None),
    language: str = Form("ru"),
    publication_type: str = Form("article"),
    doi: str | None = Form(None),
    status: str = Form("draft"),

    author_ids: str | None = Form(None),
    topic_ids: str | None = Form(None),
    keyword_ids: str | None = Form(None),

    author_names: str | None = Form(None),
    topic_names: str | None = Form(None),
    keyword_names: str | None = Form(None),

    file: UploadFile = File(...),

    db: AsyncSession = Depends(get_db),
):
    """
    Создание публикации вместе с PDF.

    Нужна для формы "Добавить публикацию",
    чтобы backend сразу создал source_file
    и положил его id в publication.source_file_id.
    """

    source_file = await save_uploaded_pdf(file, db)

    parsed_author_ids = parse_ids(author_ids)
    parsed_topic_ids = parse_ids(topic_ids)
    parsed_keyword_ids = parse_ids(keyword_ids)

    parsed_author_names = parse_names(author_names)
    parsed_topic_names = parse_names(topic_names)
    parsed_keyword_names = parse_names(keyword_names)

    authors = await resolve_authors(
        db,
        ids=parsed_author_ids,
        names=parsed_author_names,
    )
    topics = await resolve_topics(
        db,
        ids=parsed_topic_ids,
        names=parsed_topic_names,
    )
    keywords = await resolve_keywords(
        db,
        ids=parsed_keyword_ids,
        names=parsed_keyword_names,
    )

    publication = Publication(
        title=title,
        year=year,
        language=normalize_language(language),
        publication_type=normalize_publication_type(publication_type),
        doi=doi,
        status=status,
        source_file_id=source_file.id,
    )

    publication.authors = authors
    publication.topics = topics
    publication.keywords = keywords

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
        exclude={
            "author_ids",
            "topic_ids",
            "keyword_ids",
            "author_names",
            "topic_names",
            "keyword_names",
        },
    )

    if "source_file_id" in update_data:
        await check_source_file_exists(db, update_data["source_file_id"])

    if "publication_type" in update_data and update_data["publication_type"]:
        update_data["publication_type"] = normalize_publication_type(
            update_data["publication_type"]
        )

    if "language" in update_data and update_data["language"]:
        update_data["language"] = normalize_language(update_data["language"])

    for field, value in update_data.items():
        setattr(publication, field, value)

    if data.author_ids is not None or data.author_names is not None:
        publication.authors = await resolve_authors(
            db,
            ids=data.author_ids or [],
            names=data.author_names or [],
        )

    if data.topic_ids is not None or data.topic_names is not None:
        publication.topics = await resolve_topics(
            db,
            ids=data.topic_ids or [],
            names=data.topic_names or [],
        )

    if data.keyword_ids is not None or data.keyword_names is not None:
        publication.keywords = await resolve_keywords(
            db,
            ids=data.keyword_ids or [],
            names=data.keyword_names or [],
        )

    await db.commit()

    return await get_publication_or_404(publication.id, db)


@router.delete("/{publication_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_publication(
    publication_id: int,
    db: AsyncSession = Depends(get_db),
):
    publication = await get_publication_or_404(publication_id, db)
    cleanup = await delete_publication_with_resources(db, publication)
    delete_managed_upload_file(cleanup.source_file_path)
