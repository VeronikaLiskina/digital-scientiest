import asyncio
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
from app.repositories.semantic_search_repository import (
    HYBRID_TOP_K,
    SemanticSearchRepository,
)
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
from app.services.assistant_answer_service import (
    answer_text_from_blocks,
    parse_structured_rag_answer,
    question_requests_bibliography,
    single_answer_block,
    validate_human_answer,
)
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
from app.services.prompt_builder import build_rag_context, build_rag_prompt
from app.services.reranker_service import RerankerError, RerankerService
from app.services.source_relevance import (
    diversify_chunks_by_publication,
    filter_relevant_sources,
)
from app.services.publication_query_service import (
    DESCRIPTION_UNAVAILABLE,
    build_described_publication_catalog_answer,
    build_publication_catalog_answer,
    build_publication_count_answer,
    count_publications,
    get_publication_catalog,
    get_representative_descriptions,
    is_publication_catalog_question,
    is_publication_catalog_with_descriptions_question,
    is_publication_count_question,
)


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


def _source_id(chunk_id: int) -> str:
    return f"chunk-{int(chunk_id)}"


async def _translate_search_query(
    question: str,
    *,
    source_language: str,
) -> str:
    return await LocalLLMService().translate_search_query(
        question,
        source_language=source_language,
    )


def _unique_ranked_chunks(chunks: list[dict]) -> list[dict]:
    best_by_chunk_id: dict[int, dict] = {}

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


def _build_answer_sources(chunks: list[dict]) -> list[dict[str, Any]]:
    return [
        {
            "source_id": _source_id(chunk["chunk_id"]),
            "publication_id": chunk["publication_id"],
            "publication_title": chunk["publication_title"],
            "chunk_id": chunk["chunk_id"],
            "chunk_index": chunk["chunk_index"],
            "similarity": float(chunk["similarity"]),
        }
        for chunk in _unique_ranked_chunks(chunks)
    ]


def _legacy_answer_origin(message: ChatMessage) -> str | None:
    if message.answer_origin:
        return message.answer_origin
    if message.response_kind == "general_knowledge":
        return "external"
    if message.response_kind == "database":
        return "catalog" if message.catalog else "internal"
    if message.response_kind == "rag" or message.sources:
        return "internal"
    return None


def _build_conversation(messages: list[ChatMessage], *, limit: int = 8) -> str:
    recent_messages = messages[-limit:]
    labels = {"user": "Пользователь", "assistant": "Ассистент"}
    return "\n".join(
        f"{labels.get(message.role, message.role)}: {message.content}"
        for message in recent_messages
    )


def _message_read(message: ChatMessage) -> ChatMessageRead:
    sources = [
        {
            **source,
            "source_id": source.get("source_id", _source_id(source["chunk_id"])),
        }
        for source in (message.sources or [])
    ]
    answer_blocks = message.answer_blocks or []
    if message.role == "assistant" and not answer_blocks:
        answer_blocks = single_answer_block(message.content)

    return ChatMessageRead(
        id=message.id,
        chat_id=message.chat_id,
        role=message.role,
        content=message.content,
        sources=sources,
        answer_blocks=answer_blocks,
        answer_origin=_legacy_answer_origin(message),
        catalog=message.catalog,
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


def _format_author_name(full_name: str) -> str:
    return re.sub(r"(?<=\.)\s+(?=[А-ЯЁA-Z]\.)", "", full_name.strip())


async def _answer_database_question(
    *,
    question: str,
    db: AsyncSession,
    conversation: str | None,
) -> dict[str, Any] | None:
    with_descriptions = is_publication_catalog_with_descriptions_question(
        question,
        conversation,
    )
    if with_descriptions or is_publication_catalog_question(question):
        total, publications = await get_publication_catalog(db)
        descriptions = (
            await get_representative_descriptions(
                db,
                [publication.id for publication in publications],
            )
            if with_descriptions
            else {}
        )
        answer = (
            build_described_publication_catalog_answer(total, len(publications))
            if with_descriptions
            else build_publication_catalog_answer(total, len(publications))
        )
        catalog = {
            "total": total,
            "returned_count": len(publications),
            "truncated": len(publications) < total,
            "items": [
                {
                    "publication_id": publication.id,
                    "title": publication.title,
                    "year": publication.year,
                    "authors": [
                        _format_author_name(author.full_name)
                        for author in publication.authors
                    ],
                    "publication_type": publication.publication_type,
                    "publication_url": f"/publications/{publication.id}",
                    "description": (
                        descriptions.get(publication.id, DESCRIPTION_UNAVAILABLE)
                        if with_descriptions
                        else None
                    ),
                }
                for publication in publications
            ],
        }
        return {
            "question": question,
            "answer": answer,
            "sources": [],
            "answer_blocks": single_answer_block(answer),
            "answer_origin": "catalog",
            "catalog": catalog,
        }

    if is_publication_count_question(question):
        answer = build_publication_count_answer(await count_publications(db))
        return {
            "question": question,
            "answer": answer,
            "sources": [],
            "answer_blocks": single_answer_block(answer),
            "answer_origin": "internal",
            "catalog": None,
        }

    return None


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
    allow_bibliography = question_requests_bibliography(question)
    query_embedding = await asyncio.to_thread(
        embedding_service.embed_query,
        question,
    )

    repository = SemanticSearchRepository(db)
    candidate_chunks = await repository.search_chunks(
        query_embedding=query_embedding,
        embedding_model=embedding_service.model_name,
        query_text=question,
        limit=HYBRID_TOP_K,
        min_similarity=min_similarity,
    )

    async def retrieve_verified_chunks(
        search_question: str,
        candidates: list[dict] | None = None,
    ) -> list[dict]:
        nonlocal reranker_service

        if candidates is None:
            search_embedding = await asyncio.to_thread(
                embedding_service.embed_query,
                search_question,
            )
            candidates = await repository.search_chunks(
                query_embedding=search_embedding,
                embedding_model=embedding_service.model_name,
                query_text=search_question,
                limit=HYBRID_TOP_K,
                min_similarity=min_similarity,
            )

        relevant = filter_relevant_sources(
            question=search_question,
            chunks=candidates,
            limit=len(candidates),
        )
        if not relevant:
            return []

        if reranker_service is None:
            reranker_service = await asyncio.to_thread(get_reranker_service)

        reranked = await asyncio.to_thread(
            reranker_service.rerank,
            search_question,
            relevant,
            limit=limit,
        )
        return diversify_chunks_by_publication(reranked, limit)

    chunks = await retrieve_verified_chunks(question, candidate_chunks)
    translated_chunks: list[dict] = []
    try:
        translated_query = await _translate_search_query(
            question,
            source_language=expected_language,
        )
    except LocalLLMError as exc:
        logger.warning("Bilingual search query translation failed: %s", exc)
    else:
        if (
            translated_query.strip()
            and translated_query.casefold() != question.casefold()
        ):
            logger.info("Running retrieval with automatically translated query")
            translated_chunks = await retrieve_verified_chunks(translated_query)

    chunks = diversify_chunks_by_publication(
        _unique_ranked_chunks([*chunks, *translated_chunks]),
        limit,
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

    ranked_chunks = _unique_ranked_chunks(chunks)
    chunks_with_source_ids = [
        {**chunk, "source_id": _source_id(chunk["chunk_id"])}
        for chunk in ranked_chunks
    ]
    context = build_rag_context(
        chunks_with_source_ids,
        preserve_bibliography=allow_bibliography,
    )
    logger.info(
        "final_selected_chunks=%s",
        [chunk.get("chunk_id") for chunk in chunks],
    )
    prompt = build_rag_prompt(
        question,
        context,
        conversation,
        detail_percent=detail_percent,
    )
    llm_service = LocalLLMService()
    available_sources = _build_answer_sources(ranked_chunks)
    allowed_source_ids = {
        source["source_id"]
        for source in available_sources
    }

    async def generate_and_validate(generation_prompt: str) -> list[dict[str, Any]]:
        raw_answer = await llm_service.generate_answer(
            generation_prompt,
            expected_language=expected_language,
            structured_output=True,
        )
        blocks = parse_structured_rag_answer(
            raw_answer,
            allowed_source_ids=allowed_source_ids,
        )
        validate_human_answer(
            blocks,
            expected_language=expected_language,
            allow_bibliography=allow_bibliography,
        )
        return blocks

    try:
        answer_blocks = await generate_and_validate(prompt)
    except LLMGenerationError as first_exc:
        logger.warning(
            "Structured assistant answer rejected on first attempt: %s",
            first_exc,
        )
        retry_prompt = (
            f"{prompt}\n\n"
            "Предыдущий ответ не прошёл проверку качества: "
            f"{first_exc}. Сформируй ответ заново: "
            "строго на языке вопроса, естественным и содержательным текстом, без служебных "
            "ID, JSON в поле text, метаданных поиска и случайных символов. Соблюдай "
            "заданный JSON-формат всего ответа. Не копируй OCR-слова со смешением "
            "кириллицы и латиницы и не перечисляй авторов или литературу, если вопрос "
            "не просит об этом. Делай короткие смысловые блоки и ставь после каждого "
            "только 1–3 source_id, непосредственно подтверждающих его факты. Не нужно "
            "использовать все источники из контекста."
        )
        try:
            answer_blocks = await generate_and_validate(retry_prompt)
        except LLMGenerationError as second_exc:
            logger.error(
                "Structured assistant answer rejected on second attempt: %s; "
                "refusing to return an answer without precise inline citations",
                second_exc,
            )
            raise second_exc from first_exc

    source_by_id = {
        source["source_id"]: source
        for source in available_sources
    }
    used_source_ids = list(
        dict.fromkeys(
            source_id
            for block in answer_blocks
            for source_id in block["source_ids"]
        )
    )
    sources = [source_by_id[source_id] for source_id in used_source_ids]
    answer = answer_text_from_blocks(answer_blocks)
    return {
        "question": question,
        "answer": answer,
        "sources": sources,
        "answer_blocks": answer_blocks,
        "answer_origin": "internal",
        "catalog": None,
    }


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
