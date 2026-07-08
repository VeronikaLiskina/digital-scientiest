import asyncio

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.database import get_db
from app.dependencies import get_embedding_service
from app.repositories.semantic_search_repository import SemanticSearchRepository
from app.schemas.assistant import AssistantAskRequest, AssistantAskResponse
from app.services.embedding_service import EmbeddingService
from app.services.local_llm_service import LocalLLMService
from app.services.prompt_builder import (
    build_general_fallback_prompt,
    build_rag_context,
    build_rag_prompt,
)
from app.services.source_relevance import select_answer_sources


router = APIRouter(prefix="/assistant", tags=["Assistant"])


@router.post("/ask", response_model=AssistantAskResponse)
async def ask_assistant(
    data: AssistantAskRequest,
    db: AsyncSession = Depends(get_db),
    embedding_service: EmbeddingService = Depends(get_embedding_service),
):
    query_embedding = await asyncio.to_thread(
        embedding_service.embed_text,
        data.question,
    )

    repository = SemanticSearchRepository(db)
    candidate_limit = min(max(data.limit * 3, 15), 30)

    candidate_chunks = await repository.search_chunks(
        query_embedding=query_embedding,
        limit=candidate_limit,
        min_similarity=data.min_similarity,
    )
    chunks = select_answer_sources(
        question=data.question,
        chunks=candidate_chunks,
        limit=data.limit,
    )

    llm_service = LocalLLMService()

    if not chunks:
        prompt = build_general_fallback_prompt(data.question)
        answer = await llm_service.generate_answer(
            prompt,
            allow_general_knowledge=True,
        )

        return {
            "question": data.question,
            "answer": answer,
            "sources": [],
        }

    context = build_rag_context(chunks)
    prompt = build_rag_prompt(data.question, context)
    answer = await llm_service.generate_answer(prompt)

    sources = [
        {
            "publication_id": chunk["publication_id"],
            "publication_title": chunk["publication_title"],
            "chunk_id": chunk["chunk_id"],
            "chunk_index": chunk["chunk_index"],
            "text": chunk["text"],
            "similarity": chunk["similarity"],
        }
        for chunk in chunks
    ]

    return {
        "question": data.question,
        "answer": answer,
        "sources": sources,
    }
