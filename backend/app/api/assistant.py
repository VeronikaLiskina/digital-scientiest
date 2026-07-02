import asyncio

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.database import get_db
from app.dependencies import get_embedding_service
from app.repositories.semantic_search_repository import SemanticSearchRepository
from app.schemas.assistant import AssistantAskRequest, AssistantAskResponse
from app.services.embedding_service import EmbeddingService
from app.services.local_llm_service import LocalLLMService
from app.services.prompt_builder import build_rag_context, build_rag_prompt


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

    chunks = await repository.search_chunks(
        query_embedding=query_embedding,
        limit=data.limit,
        min_similarity=data.min_similarity,
    )

    if not chunks:
        return {
            "question": data.question,
            "answer": "В базе публикаций не найдено достаточно релевантных фрагментов для ответа на этот вопрос.",
            "sources": [],
        }

    context = build_rag_context(chunks)
    prompt = build_rag_prompt(data.question, context)

    llm_service = LocalLLMService()

    answer = await llm_service.generate_answer(
        question=data.question,
        context=prompt,
    )

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
