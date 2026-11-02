from __future__ import annotations

import re

from app.models.chat import Chat, ChatMessage
from app.schemas.assistant import ChatDetail, ChatMessageRead, ChatRead
from app.services.assistant_answer_service import single_answer_block


def source_id(chunk_id: int) -> str:
    return f"chunk-{int(chunk_id)}"


def build_conversation(messages: list[ChatMessage], *, limit: int = 8) -> str:
    recent_messages = messages[-limit:]
    labels = {"user": "Пользователь", "assistant": "Ассистент"}
    return "\n".join(
        f"{labels.get(message.role, message.role)}: {message.content}"
        for message in recent_messages
    )


def last_publication_context(messages: list[ChatMessage]) -> tuple[int, ...] | None:
    """Recover the selected documents from persisted response data, not prose."""
    message = next((m for m in reversed(messages) if m.role == "assistant"), None)
    if message is None or _legacy_answer_origin(message) == "external":
        return None
    if message.catalog is not None:
        return tuple(dict.fromkeys(item["publication_id"] for item in message.catalog.get("items", [])))
    if message.sources:
        return tuple(dict.fromkeys(source["publication_id"] for source in message.sources))
    return None


def contextual_search_question(question: str, conversation: str | None) -> str:
    """Resolve short follow-ups using user questions, never prior answer facts."""
    if not conversation or len(question.split()) > 18:
        return question
    continuation = re.search(
        r"(?:\b(?:она|он|ней|него|они|их|них|это|этот|этого|этому|этом|этой|эти|этих|там|этим|them|those|its)\b|"
        r"^(?:а\s+(?:как|какие|какой|когда|где|почему)|подробнее|поясни|продолжи|"
        r"and\s+(?:how|what|why)|tell me more))", question, re.I,
    )
    if continuation is None:
        return question
    previous = [line.removeprefix("Пользователь:").strip() for line in conversation.splitlines()
                if line.startswith("Пользователь:")]
    # Keep enough user context for a chain of follow-ups without feeding an
    # ever-growing history into embeddings or copying assistant assertions.
    return "\n".join([*(text[:1000] for text in previous[-2:]), question])


def message_read(message: ChatMessage) -> ChatMessageRead:
    sources = [
        {
            **source,
            "source_id": source.get("source_id", source_id(source["chunk_id"])),
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


def chat_read(chat: Chat) -> ChatRead:
    return ChatRead(
        id=chat.id,
        title=chat.title,
        created_at=chat.created_at,
        updated_at=chat.updated_at,
    )


def chat_detail(chat: Chat) -> ChatDetail:
    return ChatDetail(
        **chat_read(chat).model_dump(),
        messages=[message_read(message) for message in chat.messages],
    )


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
