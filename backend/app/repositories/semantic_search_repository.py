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
    ) -> list[dict]:
        distance = DocumentChunk.embedding.cosine_distance(query_embedding)

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
            .limit(limit)
        )

        result = await self.session.execute(stmt)
        rows = result.mappings().all()

        return [
            {
                "chunk_id": row["chunk_id"],
                "publication_id": row["publication_id"],
                "chunk_index": row["chunk_index"],
                "text": row["text"],
                "publication_title": row["publication_title"],
                "distance": float(row["distance"]),
                "similarity": float(1 - row["distance"]),
            }
            for row in rows
        ]
