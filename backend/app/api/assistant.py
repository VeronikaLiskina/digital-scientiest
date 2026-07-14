import asyncio
import re
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db.database import get_db
from app.dependencies import get_embedding_service
from app.models.chat import Chat, ChatMessage
from app.repositories.semantic_search_repository import SemanticSearchRepository
from app.schemas.assistant import (
    AssistantAskRequest,
    AssistantAskResponse,
    ChatCreate,
    ChatDetail,
    ChatMessageCreate,
    ChatMessageRead,
    ChatRead,
    ChatReply,
)
from app.services.embedding_service import EmbeddingService
from app.services.local_llm_service import LocalLLMService
from app.services.prompt_builder import (
    build_general_fallback_prompt,
    build_rag_context,
    build_rag_prompt,
)
from app.services.source_relevance import select_answer_sources


router = APIRouter(prefix="/assistant", tags=["Assistant"])

CYRILLIC_RE = re.compile(r"[А-Яа-яЁё]")


def _general_knowledge_disclaimer(question: str) -> str:
    if CYRILLIC_RE.search(question):
        return (
            "В текущих материалах я не нашёл информации для ответа на этот вопрос. "
            "Ниже — ответ из общих знаний, а не из загруженных публикаций."
        )
    return (
        "I could not find information answering this question in the current materials. "
        "The following answer is based on general knowledge, not on the uploaded publications."
    )


def _build_answer_sources(chunks: list[dict]) -> list[dict[str, Any]]:
    best_chunk_by_publication: dict[int, dict] = {}

    for chunk in chunks:
        publication_id = int(chunk["publication_id"])
        current = best_chunk_by_publication.get(publication_id)
        if current is None or float(chunk["similarity"]) > float(current["similarity"]):
            best_chunk_by_publication[publication_id] = chunk

    ranked_chunks = sorted(
        best_chunk_by_publication.values(),
        key=lambda chunk: (-float(chunk["similarity"]), int(chunk["publication_id"])),
    )

    return [
        {
            "publication_id": chunk["publication_id"],
            "publication_title": chunk["publication_title"],
            "chunk_id": chunk["chunk_id"],
            "chunk_index": chunk["chunk_index"],
            "similarity": float(chunk["similarity"]),
        }
        for chunk in ranked_chunks
    ]


def _build_conversation(messages: list[ChatMessage], *, limit: int = 8) -> str:
    recent_messages = messages[-limit:]
    labels = {"user": "Пользователь", "assistant": "Ассистент"}
    return "\n".join(
        f"{labels.get(message.role, message.role)}: {message.content}"
        for message in recent_messages
    )


def _message_read(message: ChatMessage) -> ChatMessageRead:
    return ChatMessageRead(
        id=message.id,
        chat_id=message.chat_id,
        role=message.role,
        content=message.content,
        sources=message.sources or [],
        created_at=message.created_at,
    )


def _chat_read(chat: Chat) -> ChatRead:
    return ChatRead(
        id=chat.id,
        title=chat.title,
        created_at=chat.created_at,
        updated_at=chat.updated_at,
    )


def _chat_detail(chat: Chat) -> ChatDetail:
    return ChatDetail(
        **_chat_read(chat).model_dump(),
        messages=[_message_read(message) for message in chat.messages],
    )


async def _get_chat(
    db: AsyncSession,
    chat_id: int,
    *,
    with_messages: bool = False,
) -> Chat | None:
    query = select(Chat).where(Chat.id == chat_id)
    if with_messages:
        query = query.options(selectinload(Chat.messages))

    result = await db.execute(query)
    return result.scalar_one_or_none()


async def _answer_question(
    *,
    question: str,
    limit: int,
    min_similarity: float,
    db: AsyncSession,
    embedding_service: EmbeddingService,
    conversation: str | None = None,
) -> dict[str, Any]:
    query_embedding = await asyncio.to_thread(
        embedding_service.embed_text,
        question,
    )

    repository = SemanticSearchRepository(db)
    candidate_limit = min(max(limit * 6, 30), 60)

    candidate_chunks = await repository.search_chunks(
        query_embedding=query_embedding,
        limit=candidate_limit,
        min_similarity=min_similarity,
        max_chunks_per_publication=3,
    )
    chunks = select_answer_sources(
        question=question,
        chunks=candidate_chunks,
        limit=limit,
    )

    if not chunks:
        prompt = build_general_fallback_prompt(question, conversation)
        llm_service = LocalLLMService()
        general_answer = await llm_service.generate_general_knowledge_answer(prompt)
        return {
            "question": question,
            "answer": f"{_general_knowledge_disclaimer(question)}\n\n{general_answer.strip()}",
            "sources": [],
        }

    context = build_rag_context(chunks)
    prompt = build_rag_prompt(question, context, conversation)
    llm_service = LocalLLMService()
    answer = await llm_service.generate_answer(prompt)

    sources = _build_answer_sources(chunks)
    return {"question": question, "answer": answer, "sources": sources}


@router.post("/ask", response_model=AssistantAskResponse)
async def ask_assistant(
    data: AssistantAskRequest,
    db: AsyncSession = Depends(get_db),
    embedding_service: EmbeddingService = Depends(get_embedding_service),
):
    return await _answer_question(
        question=data.question,
        limit=data.limit,
        min_similarity=data.min_similarity,
        db=db,
        embedding_service=embedding_service,
    )


@router.get("/chats", response_model=list[ChatRead])
async def get_chats(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Chat).order_by(Chat.updated_at.desc(), Chat.id.desc()))
    return [_chat_read(chat) for chat in result.scalars().all()]


@router.post("/chats", response_model=ChatDetail, status_code=status.HTTP_201_CREATED)
async def create_chat(data: ChatCreate, db: AsyncSession = Depends(get_db)):
    title = (data.title or "Новый чат").strip() or "Новый чат"
    chat = Chat(title=title[:200])
    db.add(chat)
    await db.commit()
    await db.refresh(chat)
    return ChatDetail(**_chat_read(chat).model_dump(), messages=[])


@router.get("/chats/{chat_id}", response_model=ChatDetail)
async def get_chat(chat_id: int, db: AsyncSession = Depends(get_db)):
    chat = await _get_chat(db, chat_id, with_messages=True)
    if chat is None:
        raise HTTPException(status_code=404, detail="Чат не найден")
    return _chat_detail(chat)


@router.delete("/chats/{chat_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_chat(chat_id: int, db: AsyncSession = Depends(get_db)):
    chat = await _get_chat(db, chat_id)
    if chat is None:
        raise HTTPException(status_code=404, detail="Чат не найден")
    await db.delete(chat)
    await db.commit()


@router.post("/chats/{chat_id}/messages", response_model=ChatReply)
async def send_chat_message(
    chat_id: int,
    data: ChatMessageCreate,
    db: AsyncSession = Depends(get_db),
    embedding_service: EmbeddingService = Depends(get_embedding_service),
):
    chat = await _get_chat(db, chat_id, with_messages=True)
    if chat is None:
        raise HTTPException(status_code=404, detail="Чат не найден")

    content = data.content.strip()
    conversation = _build_conversation(chat.messages)
    now = datetime.now(timezone.utc)

    if not chat.messages and chat.title == "Новый чат":
        chat.title = content[:80]

    user_message = ChatMessage(chat=chat, role="user", content=content)
    chat.updated_at = now
    db.add(user_message)
    await db.commit()
    await db.refresh(user_message)

    result = await _answer_question(
        question=content,
        limit=data.limit,
        min_similarity=data.min_similarity,
        db=db,
        embedding_service=embedding_service,
        conversation=conversation,
    )

    assistant_message = ChatMessage(
        chat_id=chat.id,
        role="assistant",
        content=result["answer"],
        sources=result["sources"],
    )
    chat.updated_at = datetime.now(timezone.utc)
    db.add(assistant_message)
    await db.commit()
    await db.refresh(chat)
    await db.refresh(assistant_message)

    return ChatReply(
        chat=_chat_read(chat),
        user_message=_message_read(user_message),
        assistant_message=_message_read(assistant_message),
    )
