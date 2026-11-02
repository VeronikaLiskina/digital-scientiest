"""General conversation routing and generation, independent of archive models."""
from __future__ import annotations

import re
from typing import Any

from app.services.assistant_answer_service import single_answer_block
from app.services.llm.base import LLMGenerationError
from app.services.local_llm_service import LocalLLMService, detect_question_language
from app.services.prompt_builder import build_general_fallback_prompt
from app.services.publication_search_service import DOCUMENT_NOUN, extract_document_reference


def requires_publication_evidence(question: str) -> bool:
    """An explicit request for archive evidence must never turn into guesses."""
    text = question.casefold().replace("ё", "е")
    if extract_document_reference(question) is not None or re.search(
        rf"\b(?:найди(?:те)?|покажи(?:те)?|открой(?:те)?|в|из|о|об|про|согласно)\s+(?:мне\s+)?{DOCUMENT_NOUN}\b", text,
    ):
        return True
    return bool(re.search(
        r"(?:\b(?:в|из|по|о|об|про|согласно)\s+(?:(?:этих|этой|этим|этого|загруженн\w*|"
        r"найденн\w*|данн\w*|наших|моих|эт\w*|научн\w*)\s+)*"
        r"(?:публикаци\w*|стать\w*|стате\w*|архив\w*|материал\w*|исследовани\w*|работ\w*|документ\w*)\b|"
        r"\b(?:статья|публикация)\s*(?:№|номер|#)\s*\d+|"
        r"\b(?:найди(?:те)?|покажи(?:те)?|открой(?:те)?)\s+(?:мне\s+)?(?:статью|публикацию|документ)\b|"
        r"\b(?:автор\w*|вывод\w*|результат\w*|цитат\w*)\b.*\b(?:стать\w*|стате\w*|публикаци\w*)\b|"
        r"\b(?:автор\w*\s+(?:пиш\w*|утвержда\w*|указ\w*)|"
        r"(?:загруженн\w*|найденн\w*)\s+(?:работ\w*|документ\w*))|"
        r"\b(?:in|from|according to)\s+(?:the\s+)?(?:(?:uploaded|these|this|provided)\s+)?"
        r"(?:papers?|publications?|articles?|archive|documents?)\b)", text,
    ))


def is_general_conversation(question: str, *, previous_origin: str | None = None) -> bool:
    text = " ".join(question.casefold().replace("ё", "е").split()).strip(" ?!.,")
    greeting = r"(?:привет(?:ик)?|здравствуй(?:те)?|доброе утро|добрый (?:день|вечер)|hello|hi|hey)"
    if re.fullmatch(greeting + r"[\s!.,]*(?:(?:как (?:у тебя )?дела|как ты|how are you))?", text):
        return True
    if re.fullmatch(r"(?:как (?:у тебя )?дела|как ты|спасибо(?: большое)?|благодарю|пока|до свидания|кто ты|что ты умеешь|thanks|thank you|bye|who are you|what can you do)", text):
        return True
    if re.search(
        r"(?:\b(?:поговорим|поболтаем|поболтать|поговорить|анекдот|шутку)\b|"
        r"из общих знаний|без (?:привязки к |использования )?(?:публикаци\w*|стать\w*|архива)|"
        r"не по публикациям|\b(?:как приготовить|придумай|сочини|помоги (?:мне )?написать)\b|"
        r"\b(?:let.s chat|tell me a joke|write a poem|general knowledge)\b)", text,
    ):
        return True
    return previous_origin == "external" and bool(re.match(
        r"^(?:а\b|и\b|еще\b|да\b|нет\b|почему\b|подробнее\b|продолжи\b|"
        r"объясни\b|расскажи\b|and\b|why\b|tell me more\b)", text,
    ))


async def answer_general_question(
    *, question: str, conversation: str | None, archive_searched: bool = False,
) -> dict[str, Any]:
    answer = await LocalLLMService().generate_general_knowledge_answer(
        build_general_fallback_prompt(question, conversation, archive_searched=archive_searched),
        expected_language=detect_question_language(question),
    )
    if not isinstance(answer, str) or not answer.strip():
        raise LLMGenerationError("Модель вернула пустой ответ в свободном диалоге")
    return {
        "question": question, "answer": answer.strip(), "sources": [],
        "answer_blocks": single_answer_block(answer.strip()),
        "answer_origin": "external", "catalog": None,
    }
