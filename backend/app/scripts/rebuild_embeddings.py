import asyncio
from datetime import datetime, timezone

from sqlalchemy import select

from app.core.config import settings
from app.db.database import async_session_maker
from app.models.document_chunk import DocumentChunk
from app.services.embedding_service import EmbeddingService


BATCH_SIZE = 16


async def rebuild_embeddings() -> None:
    embedding_service = EmbeddingService(
        settings.embedding_model_name,
        batch_size=settings.embedding_batch_size,
        cpu_threads=settings.embedding_cpu_threads,
        max_concurrent_jobs=settings.embedding_max_concurrent_jobs,
    )

    async with async_session_maker() as session:
        total_updated = 0

        while True:
            result = await session.execute(
                select(DocumentChunk)
                .where(DocumentChunk.embedding.is_(None))
                .order_by(DocumentChunk.id)
                .limit(BATCH_SIZE)
            )

            chunks = list(result.scalars().all())

            if not chunks:
                break

            texts = [chunk.chunk_text for chunk in chunks]

            embeddings = await asyncio.to_thread(
                embedding_service.embed_texts,
                texts,
            )

            now = datetime.now(timezone.utc)

            for chunk, embedding in zip(chunks, embeddings):
                chunk.embedding = embedding
                chunk.embedding_model = embedding_service.model_name
                chunk.embedded_at = now

            await session.commit()

            total_updated += len(chunks)
            print(f"Updated {total_updated} chunks")

    print("Done")


if __name__ == "__main__":
    asyncio.run(rebuild_embeddings())
