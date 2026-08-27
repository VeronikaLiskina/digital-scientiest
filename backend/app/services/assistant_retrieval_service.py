from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from typing import Any, Protocol

from app.repositories.semantic_search_repository import (
    HYBRID_TOP_K,
    SemanticSearchRepository,
)
from app.services.embedding_service import EmbeddingService
from app.services.local_llm_service import LocalLLMError
from app.services.reranker_service import RerankerService
from app.services.source_relevance import (
    diversify_chunks_by_publication,
    filter_relevant_sources,
)


logger = logging.getLogger(__name__)

MIN_BILINGUAL_FALLBACK_CHUNKS = 2
MIN_TRANSLATED_SEMANTIC_SIMILARITY = 0.8
MAX_TRANSLATED_SEMANTIC_CANDIDATES = 8


class QueryTranslator(Protocol):
    def __call__(
        self,
        question: str,
        *,
        source_language: str,
    ) -> Awaitable[str]: ...


def unique_ranked_chunks(chunks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Deduplicate chunks and preserve the strongest available ranking signal."""

    best_by_chunk_id: dict[int, dict[str, Any]] = {}

    for chunk in chunks:
        chunk_id = int(chunk["chunk_id"])
        current = best_by_chunk_id.get(chunk_id)
        chunk_rank = (
            float(chunk.get("reranker_score") or 0.0),
            float(chunk["similarity"]),
        )
        current_rank = (
            (
                float(current.get("reranker_score") or 0.0),
                float(current["similarity"]),
            )
            if current is not None
            else None
        )
        if current_rank is None or chunk_rank > current_rank:
            best_by_chunk_id[chunk_id] = chunk

    return sorted(
        best_by_chunk_id.values(),
        key=lambda chunk: (
            -float(chunk.get("reranker_score") or 0.0),
            -float(chunk["similarity"]),
            int(chunk["publication_id"]),
            int(chunk["chunk_id"]),
        ),
    )


class AssistantRetrievalService:
    """Run the retrieval process while keeping models and repositories injectable."""

    def __init__(
        self,
        *,
        repository: SemanticSearchRepository,
        embedding_service: EmbeddingService,
        reranker_factory: Callable[[], RerankerService],
        query_translator: QueryTranslator,
        reranker_service: RerankerService | None = None,
    ) -> None:
        self.repository = repository
        self.embedding_service = embedding_service
        self.reranker_factory = reranker_factory
        self.query_translator = query_translator
        self.reranker_service = reranker_service

    async def retrieve(
        self,
        *,
        question: str,
        source_language: str,
        limit: int,
        min_similarity: float,
    ) -> list[dict[str, Any]]:
        original_candidates = await self._search(question, min_similarity)
        relevant_candidates = self._apply_relevance_gate(
            question,
            original_candidates,
        )

        translated_candidates: list[dict[str, Any]] = []
        reranker_question = question
        if self._needs_bilingual_fallback(relevant_candidates):
            translated_query = await self._translate_query(
                question,
                source_language=source_language,
            )
            if translated_query:
                logger.info("Running retrieval with automatically translated query")
                translated_search_results = await self._search(
                    translated_query,
                    min_similarity,
                )
                translated_candidates = self._apply_relevance_gate(
                    translated_query,
                    translated_search_results,
                    allow_semantic_fallback=True,
                )
                if translated_candidates:
                    reranker_question = translated_query
        else:
            logger.info(
                "Skipping bilingual retrieval fallback: initial retrieval is strong"
            )

        combined_candidates = unique_ranked_chunks(
            [*relevant_candidates, *translated_candidates]
        )
        if not combined_candidates:
            return []

        reranker = await self._get_reranker()
        reranked = await asyncio.to_thread(
            reranker.rerank,
            reranker_question,
            combined_candidates,
            limit=limit,
        )
        return diversify_chunks_by_publication(reranked, limit)

    async def _search(
        self,
        question: str,
        min_similarity: float,
    ) -> list[dict[str, Any]]:
        query_embedding = await asyncio.to_thread(
            self.embedding_service.embed_query,
            question,
        )
        return await self.repository.search_chunks(
            query_embedding=query_embedding,
            embedding_model=self.embedding_service.model_name,
            query_text=question,
            limit=HYBRID_TOP_K,
            min_similarity=min_similarity,
        )

    def _apply_relevance_gate(
        self,
        question: str,
        candidates: list[dict[str, Any]],
        *,
        allow_semantic_fallback: bool = False,
    ) -> list[dict[str, Any]]:
        relevant = filter_relevant_sources(
            question=question,
            chunks=candidates,
            limit=len(candidates),
        )
        if not allow_semantic_fallback:
            return relevant

        semantic_candidates = [
            chunk
            for chunk in candidates
            if float(chunk.get("similarity") or 0.0)
            >= MIN_TRANSLATED_SEMANTIC_SIMILARITY
        ][:MAX_TRANSLATED_SEMANTIC_CANDIDATES]
        return unique_ranked_chunks(
            [*relevant, *semantic_candidates]
        )[:MAX_TRANSLATED_SEMANTIC_CANDIDATES]

    async def _translate_query(
        self,
        question: str,
        *,
        source_language: str,
    ) -> str:
        try:
            translated_query = await self.query_translator(
                question,
                source_language=source_language,
            )
        except LocalLLMError as exc:
            logger.warning("Bilingual search query translation failed: %s", exc)
            return ""

        translated_query = translated_query.strip()
        if not translated_query or translated_query.casefold() == question.casefold():
            return ""
        return translated_query

    async def _get_reranker(self) -> RerankerService:
        if self.reranker_service is None:
            self.reranker_service = await asyncio.to_thread(self.reranker_factory)
        return self.reranker_service

    @staticmethod
    def _needs_bilingual_fallback(chunks: list[dict[str, Any]]) -> bool:
        return len(chunks) < MIN_BILINGUAL_FALLBACK_CHUNKS
