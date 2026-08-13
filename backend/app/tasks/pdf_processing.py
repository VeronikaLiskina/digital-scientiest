import asyncio
from collections.abc import Coroutine
from functools import lru_cache
import os
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.exc import DBAPIError, OperationalError
from sqlalchemy.exc import TimeoutError as SQLAlchemyTimeoutError

from app.celery_app import celery_app
from app.core.config import settings
from app.db.database import async_session_maker
from app.dependencies import get_embedding_service
from app.models.publication import Publication
from app.models.source_file import SourceFile
from app.services.embedding_service import EmbeddingService
from app.services.pdf_processing import add_processing_log, process_pdf_file


_worker_event_loop: asyncio.AbstractEventLoop | None = None
_worker_event_loop_pid: int | None = None


def _run_async(coroutine: Coroutine[Any, Any, Any]) -> Any:
    """Reuse one asyncio loop inside each Celery worker process."""
    global _worker_event_loop, _worker_event_loop_pid

    process_id = os.getpid()
    if (
        _worker_event_loop is None
        or _worker_event_loop.is_closed()
        or _worker_event_loop_pid != process_id
    ):
        _worker_event_loop = asyncio.new_event_loop()
        _worker_event_loop_pid = process_id

    return _worker_event_loop.run_until_complete(coroutine)


@lru_cache(maxsize=1)
def _get_worker_embedding_service() -> EmbeddingService:
    """Load the embedding model once and reuse it for this worker process."""
    return get_embedding_service()


def is_temporary_processing_error(exc: BaseException) -> bool:
    if isinstance(
        exc,
        (
            ConnectionError,
            TimeoutError,
            OperationalError,
            SQLAlchemyTimeoutError,
            httpx.NetworkError,
            httpx.TimeoutException,
        ),
    ):
        return True

    return isinstance(exc, DBAPIError) and bool(exc.connection_invalidated)


async def _publication_id(db, source_file_id: int) -> int | None:
    return (
        await db.execute(
            select(Publication.id).where(Publication.source_file_id == source_file_id)
        )
    ).scalar_one_or_none()


async def _claim_and_process_pdf(
    source_file_id: int,
    task_id: str,
) -> dict[str, Any]:
    async with async_session_maker() as db:
        source_file = await db.get(SourceFile, source_file_id)
        if source_file is None:
            raise ValueError("Source file not found")

        await db.refresh(source_file, with_for_update=True)

        if source_file.processing_status in {"completed", "processed"}:
            return {
                "source_file_id": source_file_id,
                "status": "completed",
                "skipped": True,
            }

        if source_file.processing_status not in {"queued", "processing"}:
            return {
                "source_file_id": source_file_id,
                "status": source_file.processing_status,
                "skipped": True,
            }

        if (
            source_file.processing_task_id
            and source_file.processing_task_id != task_id
        ):
            return {
                "source_file_id": source_file_id,
                "status": source_file.processing_status,
                "skipped": True,
            }

        source_file.processing_task_id = task_id
        source_file.processing_status = "processing"
        await db.commit()

        embedding_service = await asyncio.to_thread(_get_worker_embedding_service)
        return await process_pdf_file(
            db=db,
            source_file_id=source_file_id,
            embedding_service=embedding_service,
        )


async def _mark_task_for_retry(
    source_file_id: int,
    task_id: str,
    exc: BaseException,
) -> None:
    async with async_session_maker() as db:
        source_file = await db.get(SourceFile, source_file_id)
        if source_file is None:
            return

        await db.refresh(source_file, with_for_update=True)
        if (
            source_file.processing_task_id
            and source_file.processing_task_id != task_id
        ):
            return

        source_file.processing_task_id = task_id
        source_file.processing_status = "queued"
        await db.commit()

        await add_processing_log(
            db=db,
            source_file_id=source_file_id,
            publication_id=await _publication_id(db, source_file_id),
            step_name="processing_retry_scheduled",
            status="warning",
            message="Temporary PDF processing error; retry scheduled",
            error_message=str(exc),
        )


async def _mark_task_failed(
    source_file_id: int,
    task_id: str,
    exc: BaseException,
) -> None:
    async with async_session_maker() as db:
        source_file = await db.get(SourceFile, source_file_id)
        if source_file is None:
            return

        await db.refresh(source_file, with_for_update=True)
        if (
            source_file.processing_task_id
            and source_file.processing_task_id != task_id
        ):
            return
        if source_file.processing_status == "failed":
            return

        source_file.processing_task_id = task_id
        source_file.processing_status = "failed"
        await db.commit()

        publication_id = await _publication_id(db, source_file_id)
        if publication_id is not None:
            publication = await db.get(Publication, publication_id)
            if publication is not None:
                publication.status = "review"
                await db.commit()

        await add_processing_log(
            db=db,
            source_file_id=source_file_id,
            publication_id=publication_id,
            step_name="processing_worker_failed",
            status="error",
            message="Celery worker failed to process PDF",
            error_message=str(exc),
        )


@celery_app.task(
    bind=True,
    name="app.tasks.pdf_processing.process_pdf_task",
    max_retries=settings.pdf_processing_max_retries,
)
def process_pdf_task(self, source_file_id: int) -> dict[str, Any]:
    """Process one stored PDF. The broker payload contains only its database id."""
    task_id = str(self.request.id)

    try:
        return _run_async(_claim_and_process_pdf(source_file_id, task_id))
    except Exception as exc:
        if (
            is_temporary_processing_error(exc)
            and self.request.retries < self.max_retries
        ):
            try:
                _run_async(_mark_task_for_retry(source_file_id, task_id, exc))
            except Exception:
                pass

            countdown = min(60, 2 ** (self.request.retries + 1))
            raise self.retry(exc=exc, countdown=countdown)

        try:
            _run_async(_mark_task_failed(source_file_id, task_id, exc))
        except Exception:
            pass
        raise
