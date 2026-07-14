from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.document_chunk import DocumentChunk
from app.models.publication import Publication


class SemanticSearchRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def search_chunks(
        self,
        query_embedding: list[float],
        limit: int = 10,
        min_similarity: float = 0.55,
        max_chunks_per_publication: int | None = None,
    ) -> list[dict]:
        distance = DocumentChunk.embedding.cosine_distance(query_embedding)

        # Берём широкий пул: часть результатов будет отсеяна по порогу, а часть —
        # по лимиту чанков одной публикации. Это не даёт одной большой статье
        # вытеснить остальные релевантные публикации из ответа ассистента.
        if max_chunks_per_publication is None:
            search_limit = min(limit * 3, 100)
        else:
            search_limit = min(max(limit * 5, 100), 300)

        stmt = (
            select(
                DocumentChunk.id.label("chunk_id"),
                DocumentChunk.publication_id.label("publication_id"),
                DocumentChunk.chunk_index.label("chunk_index"),
                DocumentChunk.chunk_text.label("text"),
                Publication.title.label("publication_title"),
                distance.label("distance"),
            )
            .join(Publication, Publication.id == DocumentChunk.publication_id)
            .where(DocumentChunk.embedding.is_not(None))
            .order_by(distance)
            .limit(search_limit)
        )

        result = await self.session.execute(stmt)
        rows = result.mappings().all()

        filtered_results: list[dict] = []
        publication_chunk_counts: dict[int, int] = {}

        for row in rows:
            row_distance = float(row["distance"])
            similarity = 1 - row_distance

            if similarity < min_similarity:
                continue

            publication_id = row["publication_id"]
            publication_chunk_count = publication_chunk_counts.get(publication_id, 0)
            if (
                max_chunks_per_publication is not None
                and publication_chunk_count >= max_chunks_per_publication
            ):
                continue

            filtered_results.append(
                {
                    "chunk_id": row["chunk_id"],
                    "publication_id": publication_id,
                    "chunk_index": row["chunk_index"],
                    "text": row["text"],
                    "publication_title": row["publication_title"],
                    "distance": row_distance,
                    "similarity": similarity,
                }
            )
            publication_chunk_counts[publication_id] = publication_chunk_count + 1

            if len(filtered_results) >= limit:
                break

        return filtered_results
