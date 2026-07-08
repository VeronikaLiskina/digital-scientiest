import pytest

from app.services.local_llm_service import LocalLLMService
from app.services.prompt_builder import (
    build_general_fallback_prompt,
    build_rag_context,
    build_rag_prompt,
)
from app.services.source_relevance import filter_relevant_sources, select_answer_sources


@pytest.fixture(autouse=True)
async def prepare_test_database():
    yield


class StubLLMService(LocalLLMService):
    def __init__(self, answers: list[str]) -> None:
        super().__init__()
        self.answers = answers
        self.requests: list[tuple[str, str]] = []

    async def _request_ollama(self, prompt: str, *, system_prompt: str) -> str:
        self.requests.append((prompt, system_prompt))
        return self.answers.pop(0)


async def test_generate_answer_retries_when_answer_contains_chinese_characters():
    service = StubLLMService(
        [
            "Ответ содержит 中文.",
            "Ответ переписан только на русском.",
        ]
    )

    answer = await service.generate_answer("Вопрос пользователя")

    assert answer == "Ответ переписан только на русском."
    assert len(service.requests) == 2
    assert "Предыдущий ответ содержал китайские символы" in service.requests[1][0]
    assert "Вопрос пользователя" in service.requests[1][0]


async def test_generate_answer_does_not_retry_when_answer_has_no_chinese_characters():
    service = StubLLMService(["Ответ только на русском."])

    answer = await service.generate_answer("Вопрос пользователя")

    assert answer == "Ответ только на русском."
    assert [request[0] for request in service.requests] == ["Вопрос пользователя"]


async def test_generate_answer_uses_general_system_prompt_for_fallback():
    service = StubLLMService(["Короткая общая справка."])

    await service.generate_answer(
        "В материалах не найдено.",
        allow_general_knowledge=True,
    )

    assert "Можно дать короткую справочную информацию" in service.requests[0][1]


def test_rag_prompt_contains_language_guardrails_and_source_metadata():
    context = build_rag_context(
        [
            {
                "publication_title": "Тестовая публикация",
                "publication_id": 42,
                "chunk_id": 7,
                "similarity": 0.8765,
                "text": "Фрагмент публикации.",
            }
        ]
    )
    prompt = build_rag_prompt("Что найдено?", context)

    assert "ID публикации: 42" in context
    assert "ID фрагмента: 7" in context
    assert "Сходство: 0.876" in context
    assert "Не используй китайский язык" in prompt
    assert "Не смешивай языки" in prompt
    assert "Вопрос пользователя:\nЧто найдено?" in prompt


def test_general_fallback_prompt_explains_that_materials_have_no_answer():
    prompt = build_general_fallback_prompt("байкальские нерпы")

    assert "В материалах цифрового архива не найдено" in prompt
    assert "короткий справочный ответ" in prompt
    assert "байкальские нерпы" in prompt


def test_relevance_filter_removes_semantically_near_but_unrelated_geology_sources():
    chunks = [
        {
            "publication_title": "Раннепротерозойские отложения юга Сибирского кратона",
            "text": "Фрагмент посвящен базитам, алмазоносным кимберлитовым трубкам и золотоносности.",
            "similarity": 0.66,
        }
    ]

    assert filter_relevant_sources("байкальские нерпы", chunks, limit=5) == []


def test_relevance_filter_requires_all_meaningful_terms_for_short_queries():
    chunks = [
        {
            "publication_title": "Геология Байкальского региона",
            "text": "Фрагмент посвящен геологическим структурам и минерализации.",
            "similarity": 0.66,
        }
    ]

    assert filter_relevant_sources("байкальские нерпы", chunks, limit=5) == []


def test_relevance_filter_allows_partial_short_query_match_when_similarity_is_strong():
    chunks = [
        {
            "publication_title": "Исследования Байкала",
            "text": "Фрагмент описывает эндемичные виды озера и экологические наблюдения.",
            "similarity": 0.73,
        }
    ]

    assert filter_relevant_sources("байкальские нерпы", chunks, limit=5) == chunks


def test_relevance_filter_matches_related_scientific_terms_by_shared_stem():
    chunks = [
        {
            "publication_title": "Герцинский Икатский надвиг в Забайкальском сегменте",
            "text": "Гистограмма возрастов детритовых цирконов из бластомилонита.",
            "similarity": 0.58,
        }
    ]

    assert filter_relevant_sources("герциниды", chunks, limit=5) == chunks


def test_relevance_filter_keeps_sources_with_question_terms():
    chunks = [
        {
            "publication_title": "Байкальская нерпа и озеро Байкал",
            "text": "Байкальская нерпа является эндемиком озера Байкал.",
            "similarity": 0.66,
        }
    ]

    assert filter_relevant_sources("байкальские нерпы", chunks, limit=5) == chunks


def test_answer_source_selection_falls_back_to_semantic_candidates():
    chunks = [
        {
            "publication_title": "Раннепротерозойские отложения юга Сибирского кратона",
            "text": "Фрагмент посвящен базитам, алмазоносным кимберлитовым трубкам и золотоносности.",
            "similarity": 0.66,
        }
    ]

    assert filter_relevant_sources("байкальские нерпы", chunks, limit=5) == []
    assert select_answer_sources("байкальские нерпы", chunks, limit=5) == chunks


def test_answer_source_selection_prefers_strict_relevance_when_available():
    strict_chunk = {
        "publication_title": "Байкальская нерпа и озеро Байкал",
        "text": "Байкальская нерпа является эндемиком озера Байкал.",
        "similarity": 0.66,
    }
    fallback_chunk = {
        "publication_title": "Раннепротерозойские отложения юга Сибирского кратона",
        "text": "Фрагмент посвящен базитам и золотоносности.",
        "similarity": 0.65,
    }
    chunks = [strict_chunk, fallback_chunk]

    assert select_answer_sources("байкальские нерпы", chunks, limit=5) == [
        strict_chunk
    ]
