from __future__ import annotations

import logging
from typing import Any

from app.services.assistant_answer_service import (
    answer_text_from_blocks,
    parse_structured_rag_answer,
    question_requests_bibliography,
    validate_human_answer,
)
from app.services.assistant_chat_service import source_id
from app.services.assistant_retrieval_service import unique_ranked_chunks
from app.services.local_llm_service import LLMGenerationError, LocalLLMService
from app.services.prompt_builder import build_rag_context, build_rag_prompt


logger = logging.getLogger(__name__)


def build_answer_sources(chunks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "source_id": source_id(chunk["chunk_id"]),
            "publication_id": chunk["publication_id"],
            "publication_title": chunk["publication_title"],
            "chunk_id": chunk["chunk_id"],
            "chunk_index": chunk["chunk_index"],
            "similarity": float(chunk["similarity"]),
        }
        for chunk in unique_ranked_chunks(chunks)
    ]


class AssistantGenerationService:
    """Build, generate and validate a source-grounded assistant answer."""

    def __init__(self, llm_service: LocalLLMService) -> None:
        self.llm_service = llm_service

    async def generate(
        self,
        *,
        question: str,
        expected_language: str,
        chunks: list[dict[str, Any]],
        conversation: str | None,
        detail_percent: int,
    ) -> dict[str, Any]:
        allow_bibliography = question_requests_bibliography(question)
        ranked_chunks = unique_ranked_chunks(chunks)
        chunks_with_source_ids = [
            {**chunk, "source_id": source_id(chunk["chunk_id"])}
            for chunk in ranked_chunks
        ]
        context = build_rag_context(
            chunks_with_source_ids,
            preserve_bibliography=allow_bibliography,
        )
        logger.info(
            "final_selected_chunks=%s",
            [chunk.get("chunk_id") for chunk in ranked_chunks],
        )
        prompt = build_rag_prompt(
            question,
            context,
            conversation,
            detail_percent=detail_percent,
        )
        available_sources = build_answer_sources(ranked_chunks)
        allowed_source_ids = {
            source["source_id"]
            for source in available_sources
        }

        try:
            answer_blocks = await self._generate_and_validate(
                prompt,
                expected_language=expected_language,
                allowed_source_ids=allowed_source_ids,
                allow_bibliography=allow_bibliography,
            )
        except LLMGenerationError as first_exc:
            logger.warning(
                "Structured assistant answer rejected on first attempt: %s",
                first_exc,
            )
            retry_prompt = self._build_retry_prompt(prompt, first_exc)
            try:
                answer_blocks = await self._generate_and_validate(
                    retry_prompt,
                    expected_language=expected_language,
                    allowed_source_ids=allowed_source_ids,
                    allow_bibliography=allow_bibliography,
                )
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
                used_source_id
                for block in answer_blocks
                for used_source_id in block["source_ids"]
            )
        )
        sources = [
            source_by_id[used_source_id]
            for used_source_id in used_source_ids
        ]
        return {
            "question": question,
            "answer": answer_text_from_blocks(answer_blocks),
            "sources": sources,
            "answer_blocks": answer_blocks,
            "answer_origin": "internal",
            "catalog": None,
        }

    async def _generate_and_validate(
        self,
        prompt: str,
        *,
        expected_language: str,
        allowed_source_ids: set[str],
        allow_bibliography: bool,
    ) -> list[dict[str, Any]]:
        raw_answer = await self.llm_service.generate_answer(
            prompt,
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

    @staticmethod
    def _build_retry_prompt(prompt: str, error: LLMGenerationError) -> str:
        return (
            f"{prompt}\n\n"
            "Предыдущий ответ не прошёл проверку качества: "
            f"{error}. Сформируй ответ заново: "
            "строго на языке вопроса, естественным и содержательным текстом, без служебных "
            "ID, JSON в поле text, метаданных поиска и случайных символов. Соблюдай "
            "заданный JSON-формат всего ответа. Не копируй OCR-слова со смешением "
            "кириллицы и латиницы и не перечисляй авторов или литературу, если вопрос "
            "не просит об этом. Делай короткие смысловые блоки и ставь после каждого "
            "только 1–3 source_id, непосредственно подтверждающих его факты. Не нужно "
            "использовать все источники из контекста."
        )
