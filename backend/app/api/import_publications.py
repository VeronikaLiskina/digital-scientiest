import asyncio

from fastapi import APIRouter, Depends, File, UploadFile
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db.database import get_db
from app.models.publication import Publication
from app.models.source_file import SourceFile
from app.schemas.import_publication import (
    ExtractedPublicationData,
    ImportPublicationConfirmRequest,
    ImportPublicationConfirmResult,
    PdfBatchImportItem,
)
from app.services.author_resolver import get_or_create_author
from app.services.keyword_resolver import get_or_create_keyword
from app.services.pdf_import import (
    extract_publication_metadata_from_pdf,
    save_uploaded_pdf_as_source_file,
)
from app.services.pdf_processing_queue import enqueue_pdf_processing
from app.services.topic_resolver import get_or_create_topic

router = APIRouter(prefix="/import/publications", tags=["Publication import"])


PUBLICATION_TYPE_MAP = {
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

LANGUAGE_MAP = {
    "ru": "ru",
    "rus": "ru",
    "russian": "ru",
    "русский": "ru",
    "en": "en",
    "eng": "en",
    "english": "en",
    "английский": "en",
}


def normalize_publication_type(value: str | None) -> str | None:
    if not value:
        return None

    return PUBLICATION_TYPE_MAP.get(value.strip().lower(), value)


def normalize_language(value: str | None) -> str | None:
    if not value:
        return None

    return LANGUAGE_MAP.get(value.strip().lower(), value)


def publication_load_options():
    return (
        selectinload(Publication.authors),
        selectinload(Publication.topics),
        selectinload(Publication.keywords),
    )


async def get_publication_with_relations(
    db: AsyncSession,
    publication_id: int,
) -> Publication:
    result = await db.execute(
        select(Publication)
        .where(Publication.id == publication_id)
        .options(*publication_load_options())
    )
    return result.scalar_one()


async def find_existing_publication(
    db: AsyncSession,
    *,
    source_file_id: int,
    title: str,
    year: int | None,
    doi: str | None,
) -> Publication | None:
    source_result = await db.execute(
        select(Publication).where(Publication.source_file_id == source_file_id)
    )
    existing_by_source = source_result.scalar_one_or_none()

    if existing_by_source is not None:
        return existing_by_source

    if doi:
        doi_result = await db.execute(
            select(Publication).where(Publication.doi == doi.strip())
        )
        existing_by_doi = doi_result.scalar_one_or_none()

        if existing_by_doi is not None:
            return existing_by_doi

    title_result = await db.execute(
        select(Publication).where(
            func.lower(Publication.title) == title.strip().lower(),
            Publication.year == year,
        )
    )
    return title_result.scalar_one_or_none()


@router.post("/pdf-batch", response_model=list[PdfBatchImportItem])
async def import_pdf_batch(
    files: list[UploadFile] = File(...),
    db: AsyncSession = Depends(get_db),
):
    results: list[PdfBatchImportItem] = []

    for file in files:
        filename = file.filename or "publication.pdf"

        try:
            source_file, is_duplicate = await save_uploaded_pdf_as_source_file(
                db=db,
                file=file,
                comment="Файл загружен через множественный импорт PDF",
                fail_on_duplicate=False,
            )

            if is_duplicate:
                results.append(
                    PdfBatchImportItem(
                        filename=filename,
                        status="duplicate_file",
                        source_file_id=source_file.id,
                        message="Такой PDF уже загружался",
                    )
                )
                await db.commit()
                continue

            extracted = await asyncio.to_thread(
                extract_publication_metadata_from_pdf,
                source_file.file_path,
            )

            results.append(
                PdfBatchImportItem(
                    filename=filename,
                    status="ready_to_create",
                    source_file_id=source_file.id,
                    extracted=ExtractedPublicationData(
                        title=extracted.title,
                        title_source=extracted.title_source,
                        title_confidence=extracted.title_confidence,
                        title_warning=extracted.title_warning,
                        year=extracted.year,
                        language=extracted.language,
                        publication_type=extracted.publication_type,
                        doi=extracted.doi,
                        authors=extracted.authors,
                        keywords=extracted.keywords,
                        topics=extracted.topics,
                    ),
                )
            )
            await db.commit()

        except Exception as exc:
            await db.rollback()
            results.append(
                PdfBatchImportItem(
                    filename=filename,
                    status="error",
                    message=str(exc),
                )
            )

    return results


@router.post("/confirm", response_model=list[ImportPublicationConfirmResult])
async def confirm_publication_import(
    data: ImportPublicationConfirmRequest,
    db: AsyncSession = Depends(get_db),
):
    results: list[ImportPublicationConfirmResult] = []

    for item in data.items:
        try:
            source_file = await db.get(SourceFile, item.source_file_id)

            if source_file is None:
                results.append(
                    ImportPublicationConfirmResult(
                        source_file_id=item.source_file_id,
                        status="error",
                        message="Source file not found",
                    )
                )
                continue

            existing_publication = await find_existing_publication(
                db=db,
                source_file_id=item.source_file_id,
                title=item.title,
                year=item.year,
                doi=item.doi,
            )

            if existing_publication is not None:
                results.append(
                    ImportPublicationConfirmResult(
                        source_file_id=item.source_file_id,
                        status="duplicate_publication",
                        publication_id=existing_publication.id,
                        message="Публикация уже существует",
                    )
                )
                continue

            publication = Publication(
                source_file_id=item.source_file_id,
                title=item.title.strip(),
                year=item.year,
                language=normalize_language(item.language),
                publication_type=normalize_publication_type(item.publication_type),
                doi=item.doi.strip() if item.doi else None,
                status=item.status,
            )

            db.add(publication)
            await db.flush()

            for author_name in item.authors:
                if author_name.strip():
                    publication.authors.append(
                        await get_or_create_author(db, author_name)
                    )

            for topic_name in item.topics:
                if topic_name.strip():
                    publication.topics.append(
                        await get_or_create_topic(db, topic_name)
                    )

            for keyword_name in item.keywords:
                if keyword_name.strip():
                    publication.keywords.append(
                        await get_or_create_keyword(db, keyword_name)
                    )

            source_file.processing_status = "requires_review"

            await db.commit()
            await enqueue_pdf_processing(
                db,
                item.source_file_id,
                skip_processed=True,
            )
            loaded_publication = await get_publication_with_relations(
                db=db,
                publication_id=publication.id,
            )

            results.append(
                ImportPublicationConfirmResult(
                    source_file_id=item.source_file_id,
                    status="created",
                    publication_id=publication.id,
                    publication=loaded_publication,
                )
            )

        except Exception as exc:
            await db.rollback()
            results.append(
                ImportPublicationConfirmResult(
                    source_file_id=item.source_file_id,
                    status="error",
                    message=str(exc),
                )
            )

    return results
