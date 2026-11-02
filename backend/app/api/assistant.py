import asyncio
import logging
import re
import time
from collections import OrderedDict
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db.database import get_db
from app.core.config import settings
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
    AssistantMode,
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
    contextual_search_question,
    last_publication_context,
)
from app.services.assistant_generation_service import (
    AssistantGenerationService,
)
from app.services.embedding_service import EmbeddingService
from app.services.llm.base import (
    LLMAccessDeniedError,
    LLMConfigurationError,
    LLMGenerationError,
    LLMRateLimitError,
    LLMTimeoutError,
    LLMUnavailableError,
    LocalLLMError,
)
from app.services.local_llm_service import LocalLLMService, detect_question_language
from app.services.assistant_retrieval_service import (
    AssistantRetrievalService,
)
from app.services.assistant_conversation_service import (
    answer_general_question, is_general_conversation, requires_publication_evidence,
)
from app.services.reranker_service import RerankerError, RerankerService
from app.services.llm.fallback import LLMFallbackError
from app.services.publication_search_service import (
    PublicationSearch, extract_document_reference, search_publications,
)


router = APIRouter(prefix="/assistant", tags=["Assistant"])
logger = logging.getLogger(__name__)
_translation_cache: OrderedDict[tuple[str, ...], tuple[float, str]] = OrderedDict()
TRANSLATION_CACHE_TTL_SECONDS = 600
TRANSLATION_CACHE_MAX_ENTRIES = 128

CYRILLIC_RE = re.compile(r"[А-Яа-яЁё]")


def _assistant_http_error(exc: LocalLLMError) -> HTTPException:
    # Provider messages can contain submitted text. Log only diagnostic metadata,
    # never the prompt, API key, response body or exception traceback.
    cause = exc.__cause__
    provider_status = getattr(exc, "provider_status", None) or getattr(cause, "status_code", None)
    logger.warning(
        "Assistant model request failed: error=%s provider_status=%s provider_error_code=%s",
        type(exc).__name__,
        provider_status,
        getattr(exc, "provider_error_code", None),
    )
    if isinstance(exc, LLMFallbackError):
        status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        detail = {
            "code": "llm_fallback_failed", "title": "Основная и резервная модели недоступны",
            "message": "API не подготовил ответ, локальная модель тоже не ответила. Проверьте, запущена ли Ollama и установлена ли резервная модель.",
            "retryable": True,
        }
    elif isinstance(exc, LLMAccessDeniedError):
        status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        detail = {
            "code": "llm_access_denied",
            "title": "Сервис модели отклонил запрос",
            "message": (
                "API модели вернул отказ в доступе (HTTP 403). Попробуйте повторить запрос. "
                "Если ошибка повторяется, проверьте доступ к сервису и разрешения модели."
            ),
            "retryable": True,
        }
    elif isinstance(exc, LLMConfigurationError):
        status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        detail = {
            "code": "llm_configuration_error",
            "title": "Нет доступа к модели",
            "message": (
                "Проверьте настройки API и доступ к выбранной модели. "
                "Сервис мог отклонить запрос, даже если ранее подключение работало."
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
    # This is a standalone search query, already resolved from chat context.
    # Translation does not depend on the corpus; retrieval still runs every time.
    key = (settings.llm_provider, settings.active_llm_model, settings.llm_api_base_url,
           source_language, question)
    cached = _translation_cache.get(key)
    if cached is not None and cached[0] > time.monotonic():
        _translation_cache.move_to_end(key)
        return cached[1]
    translated = await LocalLLMService().translate_search_query(
        question,
        source_language=source_language,
    )
    # Failed and empty translations must be retried once the API recovers.
    if translated.strip() and translated.casefold() != question.casefold():
        _translation_cache[key] = (time.monotonic() + TRANSLATION_CACHE_TTL_SECONDS, translated)
        _translation_cache.move_to_end(key)
        while len(_translation_cache) > TRANSLATION_CACHE_MAX_ENTRIES:
            _translation_cache.popitem(last=False)
    return translated


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
    mode: AssistantMode = "auto",
    previous_origin: str | None = None,
    publication_context: tuple[int, ...] | None = None,
) -> dict[str, Any]:
    catalog_options = {"publication_context": publication_context} if publication_context is not None else {}
    database_answer = await _answer_database_question(
        question=question,
        db=db,
        conversation=conversation,
        **catalog_options,
    )
    if database_answer is not None:
        logger.info("Assistant route=catalog origin=%s", database_answer["answer_origin"])
        return database_answer

    reference = extract_document_reference(question)
    source_scope = None
    if reference is not None and not reference.catalog_request:
        _, publications = await search_publications(db, PublicationSearch(title=reference.title))
        source_scope = tuple(p.id for p in publications)
    elif mode != "general" and publication_context is not None and contextual_search_question(question, conversation) != question:
        source_scope = publication_context

    strict_archive = (
        mode == "publications" or requires_publication_evidence(question)
        or source_scope is not None
        or (previous_origin == "catalog" and contextual_search_question(question, conversation) != question)
    )
    if (mode == "general" and source_scope is None) or (not strict_archive and is_general_conversation(question, previous_origin=previous_origin)):
        logger.info("Assistant route=general")
        return await answer_general_question(question=question, conversation=conversation)

    if source_scope == ():
        logger.info("Assistant route=missing_document")
        answer = _insufficient_information_answer(question)
        return {"question": question, "answer": answer, "sources": [],
                "answer_blocks": single_answer_block(answer), "answer_origin": "internal", "catalog": None}

    if embedding_service is None:
        embedding_service = await asyncio.to_thread(get_embedding_service)

    expected_language = detect_question_language(question)
    search_question = contextual_search_question(question, conversation)
    if search_question != question:
        try:
            search_question = await LocalLLMService().rewrite_followup_query(question, search_question)
        except LocalLLMError as exc:
            logger.warning("Follow-up query rewrite failed: error=%s", type(exc).__name__)
    repository = (SemanticSearchRepository(db, publication_ids=source_scope)
                  if source_scope is not None else SemanticSearchRepository(db))
    logger.info("Assistant route=retrieval scoped_publications=%s", source_scope)
    retrieval_service = AssistantRetrievalService(
        repository=repository,
        embedding_service=embedding_service,
        reranker_factory=get_reranker_service,
        query_translator=_translate_search_query,
        reranker_service=reranker_service,
    )
    chunks = await retrieval_service.retrieve(
        question=search_question,
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
        if not strict_archive:
            return await answer_general_question(question=question, conversation=conversation, archive_searched=True)
        answer = _insufficient_information_answer(question)
        return {
            "question": question,
            "answer": answer,
            "sources": [],
            "answer_blocks": single_answer_block(answer),
            "answer_origin": "internal",
            "catalog": None,
        }

    result = await AssistantGenerationService(LocalLLMService()).generate(
        question=question,
        expected_language=expected_language,
        chunks=chunks,
        conversation=conversation,
        detail_percent=detail_percent,
    )
    if not result["sources"] and not strict_archive:
        return await answer_general_question(question=question, conversation=conversation, archive_searched=True)
    return result


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
            mode=data.mode,
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
    previous_origin = next((message.answer_origin for message in reversed(chat.messages) if message.role == "assistant"), None)
    publication_context = last_publication_context(chat.messages)
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
            mode=data.mode,
            previous_origin=previous_origin,
            publication_context=publication_context,
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
