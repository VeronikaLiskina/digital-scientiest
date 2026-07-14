import asyncio

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.database import async_session_maker
from app.dependencies import get_embedding_service
from app.models.publication import Publication
from app.models.publication_import import ImportItem
from app.models.source_file import SourceFile
from app.models.document_chunk import DocumentChunk
from app.services.pdf_processing import add_processing_log, process_pdf_file


_processing_tasks: set[asyncio.Task[None]] = set()
_embedding_service_lock = asyncio.Lock()


async def _process_source_file_in_background(source_file_id: int) -> None:
    try:
        async with async_session_maker() as db:
            source_file = await db.get(SourceFile, source_file_id)
            if source_file is None:
                return

            source_file.processing_status = "processing"
            await db.commit()

            async with _embedding_service_lock:
                embedding_service = await asyncio.to_thread(get_embedding_service)
            await process_pdf_file(
                db=db,
                source_file_id=source_file_id,
                embedding_service=embedding_service,
            )
    except Exception as exc:
        # process_pdf_file logs its own failures. This branch also makes failures
        # during embedding-service startup visible instead of leaving "queued"
        # forever without a diagnostic record.
        async with async_session_maker() as db:
            source_file = await db.get(SourceFile, source_file_id)
            if source_file is None or source_file.processing_status == "error":
                return

            source_file.processing_status = "error"
            await db.commit()

            publication_id = (
                await db.execute(
                    select(Publication.id).where(
                        Publication.source_file_id == source_file_id
                    )
                )
            ).scalar_one_or_none()
            if publication_id is not None:
                publication = await db.get(Publication, publication_id)
                if publication is not None:
                    publication.status = "review"
                    await db.commit()

            await add_processing_log(
                db=db,
                source_file_id=source_file_id,
                publication_id=publication_id,
                step_name="processing_start_failed",
                status="error",
                message="PDF background processing failed to start",
                error_message=str(exc),
            )


def _start_processing_task(source_file_id: int) -> None:
    task = asyncio.create_task(_process_source_file_in_background(source_file_id))
    _processing_tasks.add(task)
    task.add_done_callback(_processing_tasks.discard)


async def enqueue_pdf_processing(
    db: AsyncSession,
    source_file_id: int,
    *,
    skip_processed: bool = False,
) -> str:
    """Persist the queued state before starting PDF chunking in the background."""
    source_file = await db.get(SourceFile, source_file_id)
    if source_file is None:
        raise ValueError("Source file not found")

    statuses_to_skip = {"queued", "processing"}
    if skip_processed:
        statuses_to_skip.add("processed")

    if source_file.processing_status in statuses_to_skip:
        return source_file.processing_status

    source_file.processing_status = "queued"
    await db.commit()
    _start_processing_task(source_file_id)
    return "queued"


async def recover_saved_imports_without_chunks() -> list[int]:
    """Requeue saved bulk-import publications left without chunks after a restart."""
    async with async_session_maker() as db:
        source_file_ids = list(
            (
                await db.execute(
                    select(SourceFile.id)
                    .join(ImportItem, ImportItem.source_file_id == SourceFile.id)
                    .join(Publication, Publication.id == ImportItem.publication_id)
                    .outerjoin(
                        DocumentChunk,
                        DocumentChunk.publication_id == Publication.id,
                    )
                    .where(ImportItem.status == "saved")
                    .group_by(SourceFile.id)
                    .having(func.count(DocumentChunk.id) == 0)
                    .order_by(SourceFile.id)
                )
            ).scalars().all()
        )

        for source_file_id in source_file_ids:
            source_file = await db.get(SourceFile, source_file_id)
            if source_file is None:
                continue

            # queued/processing belongs to the previous process and no longer has
            # a live asyncio task after application restart.
            if source_file.processing_status in {"queued", "processing"}:
                source_file.processing_status = "requires_review"
                await db.commit()

            await enqueue_pdf_processing(
                db,
                source_file_id,
                skip_processed=False,
            )

        return source_file_ids
