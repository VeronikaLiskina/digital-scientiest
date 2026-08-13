import asyncio
import argparse
from datetime import datetime, timezone

from sqlalchemy import func, or_, select, update

from app.core.config import settings
from app.core.embedding_models import SUPPORTED_EMBEDDING_MODELS
from app.db.database import async_session_maker
from app.models.document_chunk import DocumentChunk
from app.services.embedding_service import EmbeddingService


BATCH_SIZE = 16


async def rebuild_embeddings(
    *,
    model_name: str | None = None,
    rebuild_batch_size: int = BATCH_SIZE,
    session_factory=async_session_maker,
    embedding_service: EmbeddingService | None = None,
) -> None:
    target_model = model_name or settings.embedding_model_name
    if embedding_service is None:
        embedding_service = EmbeddingService(
            target_model,
            batch_size=settings.embedding_batch_size,
            cpu_threads=settings.embedding_cpu_threads,
            max_concurrent_jobs=settings.embedding_max_concurrent_jobs,
        )
    elif embedding_service.model_name != target_model:
        raise ValueError("Embedding service model does not match the target model")

    async with session_factory() as session:
        total_chunks = await session.scalar(select(func.count(DocumentChunk.id)))
        stale_chunks = await session.scalar(
            select(func.count(DocumentChunk.id)).where(
                or_(
                    DocumentChunk.embedding.is_(None),
                    DocumentChunk.embedding_model.is_distinct_from(target_model),
                )
            )
        )

        # A chunk has a single vector column. Remove every vector belonging to a
        # different model in one transaction before writing target-model data,
        # so the database never contains a mixed searchable corpus.
        if stale_chunks:
            await session.execute(
                update(DocumentChunk)
                .where(DocumentChunk.embedding_model.is_distinct_from(target_model))
                .values(
                    embedding=None,
                    embedding_model=None,
                    embedded_at=None,
                )
            )
            await session.commit()

        print(
            f"Target model: {target_model}; chunks: {total_chunks or 0}; "
            f"scheduled: {stale_chunks or 0}"
        )
        total_updated = 0

        while True:
            result = await session.execute(
                select(DocumentChunk)
                .where(DocumentChunk.embedding.is_(None))
                .order_by(DocumentChunk.id)
                .limit(max(1, rebuild_batch_size))
            )

            chunks = list(result.scalars().all())

            if not chunks:
                break

            texts = [chunk.chunk_text for chunk in chunks]

            embeddings = await asyncio.to_thread(
                embedding_service.embed_documents,
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
    parser = argparse.ArgumentParser(
        description="Recreate document chunk embeddings for one supported model."
    )
    parser.add_argument(
        "--model-name",
        choices=tuple(SUPPORTED_EMBEDDING_MODELS),
        default=settings.embedding_model_name,
    )
    parser.add_argument("--batch-size", type=int, default=BATCH_SIZE)
    args = parser.parse_args()
    asyncio.run(
        rebuild_embeddings(
            model_name=args.model_name,
            rebuild_batch_size=args.batch_size,
        )
    )
