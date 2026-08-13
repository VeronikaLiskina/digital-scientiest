from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.database import async_session_maker
from app.models.document_chunk import DocumentChunk
from app.models.publication import Publication
from app.models.publication_import import ImportItem
from app.models.source_file import SourceFile
from app.services.pdf_processing import add_processing_log
from app.tasks.pdf_processing import process_pdf_task


class PdfProcessingQueueError(RuntimeError):
    """The broker did not accept a PDF processing task."""


@dataclass(frozen=True)
class PdfProcessingEnqueueResult:
    task_id: str | None
    source_file_id: int
    status: str


async def enqueue_pdf_processing(
    db: AsyncSession,
    source_file_id: int,
    *,
    skip_processed: bool = False,
) -> PdfProcessingEnqueueResult:
    """Atomically persist queued state and publish one id-only Celery task."""
    source_file = await db.get(SourceFile, source_file_id)
    if source_file is None:
        raise ValueError("Source file not found")

    await db.refresh(source_file, with_for_update=True)

    # "processed" is the legacy equivalent of "completed". Never publish a
    # second task for either state, even when an older caller omits the flag.
    statuses_to_skip = {"queued", "processing", "completed", "processed"}

    if source_file.processing_status in statuses_to_skip:
        status = (
            "completed"
            if source_file.processing_status == "processed"
            else source_file.processing_status
        )
        return PdfProcessingEnqueueResult(
            task_id=source_file.processing_task_id,
            source_file_id=source_file_id,
            status=status,
        )

    source_file.processing_status = "queued"
    await db.flush()

    try:
        celery_result = process_pdf_task.delay(source_file_id)
    except Exception as exc:
        await db.rollback()
        source_file = await db.get(SourceFile, source_file_id)
        if source_file is not None:
            source_file.processing_status = "failed"
            source_file.processing_task_id = None
            await db.commit()

            publication_id = (
                await db.execute(
                    select(Publication.id).where(
                        Publication.source_file_id == source_file_id
                    )
                )
            ).scalar_one_or_none()
            await add_processing_log(
                db=db,
                source_file_id=source_file_id,
                publication_id=publication_id,
                step_name="processing_enqueue_failed",
                status="error",
                message="Failed to enqueue PDF processing task",
                error_message=str(exc),
            )

        raise PdfProcessingQueueError("PDF processing broker is unavailable") from exc

    source_file.processing_task_id = celery_result.id
    await db.commit()

    return PdfProcessingEnqueueResult(
        task_id=celery_result.id,
        source_file_id=source_file_id,
        status="queued",
    )


async def recover_saved_imports_without_chunks() -> list[int]:
    """Queue saved imports that have no chunks and no active Celery task."""
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
                    .where(
                        ImportItem.status == "saved",
                        SourceFile.processing_status.not_in(
                            {"queued", "processing", "completed", "processed"}
                        ),
                    )
                    .group_by(SourceFile.id)
                    .having(func.count(DocumentChunk.id) == 0)
                    .order_by(SourceFile.id)
                )
            ).scalars().all()
        )

        for source_file_id in source_file_ids:
            await enqueue_pdf_processing(
                db,
                source_file_id,
                skip_processed=True,
            )

        return source_file_ids
