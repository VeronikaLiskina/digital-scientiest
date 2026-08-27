import logging
import re
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db.database import get_db
from app.dependencies import get_embedding_service, get_reranker_service
from app.models.chat import Chat, ChatMessage
from app.repositories.semantic_search_repository import SemanticSearchRepository
from app.schemas.assistant import (
    AssistantAskRequest,
    AssistantAskResponse,
    ChatCreate,
    ChatDetail,
    ChatMessageCreate,
    ChatRead,
    ChatReply,
)
from app.services.assistant_answer_service import single_answer_block
from app.services.assistant_catalog_service import (
    answer_database_question as _answer_database_question,
)
from app.services.assistant_chat_service import (
    build_conversation as _build_conversation,
    chat_detail as _chat_detail,
    chat_read as _chat_read,
    message_read as _message_read,
)
from app.services.assistant_generation_service import (
    AssistantGenerationService,
    build_answer_sources as _build_answer_sources,
)
from app.services.embedding_service import EmbeddingService
from app.services.local_llm_service import (
    LLMConfigurationError,
    LLMGenerationError,
    LLMRateLimitError,
    LLMTimeoutError,
    LLMUnavailableError,
    LocalLLMError,
    LocalLLMService,
    detect_question_language,
)
from app.services.assistant_retrieval_service import (
    AssistantRetrievalService,
)
from app.services.reranker_service import RerankerError, RerankerService


router = APIRouter(prefix="/assistant", tags=["Assistant"])
logger = logging.getLogger(__name__)

CYRILLIC_RE = re.compile(r"[А-Яа-яЁё]")


def _assistant_http_error(exc: LocalLLMError) -> HTTPException:
    if isinstance(exc, LLMConfigurationError):
        status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        detail = {
            "code": "llm_configuration_error",
            "title": "Ассистент не настроен",
            "message": (
                "Проверьте выбранный LLM-провайдер, API-ключ и доступ к модели."
            ),
            "retryable": False,
        }
    elif isinstance(exc, LLMRateLimitError):
        status_code = status.HTTP_429_TOO_MANY_REQUESTS
        detail = {
            "code": "llm_rate_limited",
            "title": "Временный лимит запросов",
            "message": (
                "Квота облачной модели временно исчерпана. Повторите запрос позже."
            ),
            "retryable": True,
        }
    elif isinstance(exc, LLMTimeoutError):
        status_code = status.HTTP_504_GATEWAY_TIMEOUT
        detail = {
            "code": "llm_timeout",
            "title": "Ответ занял слишком много времени",
            "message": (
                "Модель не успела завершить ответ. Попробуйте повторить запрос "
                "или сформулировать его короче."
            ),
            "retryable": True,
        }
    elif isinstance(exc, LLMUnavailableError):
        status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        detail = {
            "code": "llm_unavailable",
            "title": "Ассистент временно недоступен",
            "message": (
                "Не удалось подключиться к выбранной модели. Повторите запрос позже."
            ),
            "retryable": True,
        }
    elif isinstance(exc, LLMGenerationError):
        status_code = status.HTTP_502_BAD_GATEWAY
        detail = {
            "code": "generation_failed",
            "title": "Не удалось подготовить ответ",
            "message": (
                "Модель вернула некорректный результат. Повторите запрос — "
                "обычно это временная ошибка."
            ),
            "retryable": True,
        }
    else:
        status_code = status.HTTP_502_BAD_GATEWAY
        detail = {
            "code": "assistant_failed",
            "title": "Не удалось получить ответ",
            "message": "Повторите запрос через несколько секунд.",
            "retryable": True,
        }

    return HTTPException(status_code=status_code, detail=detail)


def _reranker_http_error(exc: RerankerError) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail={
            "code": "reranker_unavailable",
            "title": "Проверка источников временно недоступна",
            "message": (
                "Не удалось безопасно проверить найденные фрагменты. "
                "Попробуйте повторить запрос позже."
            ),
            "retryable": True,
        },
    )


def _insufficient_information_answer(question: str) -> str:
    if CYRILLIC_RE.search(question):
        return (
            "В текущих материалах недостаточно информации для ответа на этот вопрос. "
            "Уточните запрос или загрузите дополнительные публикации."
        )
    return (
        "The current materials do not contain enough information to answer this question. "
        "Please clarify the request or add more publications."
    )


async def _translate_search_query(
    question: str,
    *,
    source_language: str,
) -> str:
    return await LocalLLMService().translate_search_query(
        question,
        source_language=source_language,
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
    embedding_service: EmbeddingService | None = None,
    reranker_service: RerankerService | None = None,
    conversation: str | None = None,
    detail_percent: int = 100,
) -> dict[str, Any]:
    database_answer = await _answer_database_question(
        question=question,
        db=db,
        conversation=conversation,
    )
    if database_answer is not None:
        return database_answer

    if embedding_service is None:
        embedding_service = get_embedding_service()

    expected_language = detect_question_language(question)
    retrieval_service = AssistantRetrievalService(
        repository=SemanticSearchRepository(db),
        embedding_service=embedding_service,
        reranker_factory=get_reranker_service,
        query_translator=_translate_search_query,
        reranker_service=reranker_service,
    )
    chunks = await retrieval_service.retrieve(
        question=question,
        source_language=expected_language,
        limit=limit,
        min_similarity=min_similarity,
    )

    logger.info(
        "reranked_chunks=%s",
        [
            {
                "chunk_id": chunk.get("chunk_id"),
                "score": round(float(chunk.get("reranker_score") or 0.0), 4),
            }
            for chunk in chunks
        ],
    )

    if not chunks:
        answer = _insufficient_information_answer(question)
        return {
            "question": question,
            "answer": answer,
            "sources": [],
            "answer_blocks": single_answer_block(answer),
            "answer_origin": "internal",
            "catalog": None,
        }

    return await AssistantGenerationService(LocalLLMService()).generate(
        question=question,
        expected_language=expected_language,
        chunks=chunks,
        conversation=conversation,
        detail_percent=detail_percent,
    )


@router.post("/ask", response_model=AssistantAskResponse)
async def ask_assistant(
    data: AssistantAskRequest,
    db: AsyncSession = Depends(get_db),
):
    try:
        return await _answer_question(
            question=data.question,
            limit=data.limit,
            min_similarity=data.min_similarity,
            detail_percent=data.detail_percent,
            db=db,
        )
    except LocalLLMError as exc:
        raise _assistant_http_error(exc) from exc
    except RerankerError as exc:
        raise _reranker_http_error(exc) from exc


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
    await db.flush()

    try:
        result = await _answer_question(
            question=content,
            limit=data.limit,
            min_similarity=data.min_similarity,
            detail_percent=data.detail_percent,
            db=db,
            conversation=conversation,
        )
    except LocalLLMError as exc:
        await db.rollback()
        raise _assistant_http_error(exc) from exc
    except RerankerError as exc:
        await db.rollback()
        raise _reranker_http_error(exc) from exc

    assistant_message = ChatMessage(
        chat_id=chat.id,
        role="assistant",
        content=result["answer"],
        sources=result["sources"],
        response_kind={
            "internal": "rag" if result["sources"] else "database",
            "external": "general_knowledge",
            "catalog": "database",
        }[result["answer_origin"]],
        catalog=result["catalog"],
        answer_origin=result["answer_origin"],
        answer_blocks=result["answer_blocks"],
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
