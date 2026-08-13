from sqlalchemy import func, select

from app.db.database import async_session_maker
from app.models.document_chunk import DocumentChunk
from app.models.publication import Publication
from app.models.source_file import SourceFile


def status_for_pdf_state(processing_status: str, chunk_count: int) -> str:
    if processing_status in {"completed", "processed"} and chunk_count > 0:
        return "processed"
    return "review"


async def synchronize_publication_statuses() -> int:
    """Align publication statuses with the actual PDF/chunk processing state."""
    async with async_session_maker() as db:
        rows = (
            await db.execute(
                select(
                    Publication,
                    SourceFile.processing_status,
                    func.count(DocumentChunk.id).label("chunk_count"),
                )
                .join(SourceFile, SourceFile.id == Publication.source_file_id)
                .outerjoin(
                    DocumentChunk,
                    DocumentChunk.publication_id == Publication.id,
                )
                .group_by(Publication.id, SourceFile.processing_status)
            )
        ).all()

        changed_count = 0
        for publication, processing_status, chunk_count in rows:
            expected_status = status_for_pdf_state(processing_status, chunk_count)
            if publication.status == expected_status:
                continue

            publication.status = expected_status
            changed_count += 1

        if changed_count:
            await db.commit()

        return changed_count
