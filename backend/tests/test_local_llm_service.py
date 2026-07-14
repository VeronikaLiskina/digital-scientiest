import pytest

from app.api import assistant
from app.schemas.assistant import AssistantAskResponse
from app.services.local_llm_service import (
    GENERAL_KNOWLEDGE_SYSTEM_PROMPT,
    LocalLLMService,
    RAG_SYSTEM_PROMPT,
)
from app.services.prompt_builder import (
    build_general_fallback_prompt,
    build_rag_context,
    build_rag_prompt,
)
from app.services.source_relevance import (
    diversify_chunks_by_publication,
    filter_relevant_sources,
    select_answer_sources,
)


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


class StubEmbeddingService:
    def embed_text(self, _text: str) -> list[float]:
        return [0.1, 0.2]


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


async def test_generate_answer_always_uses_strict_rag_system_prompt():
    service = StubLLMService(["Ответ из контекста."])

    await service.generate_answer("Вопрос с найденными фрагментами")

    assert service.requests[0][1] == RAG_SYSTEM_PROMPT
    assert "Единственный допустимый источник фактов" in service.requests[0][1]
    assert "Не используй собственные знания" in service.requests[0][1]


async def test_general_knowledge_answer_uses_separate_disclosed_mode():
    service = StubLLMService(["Общая справка."])

    await service.generate_general_knowledge_answer("Вопрос без источников")

    assert service.requests[0][1] == GENERAL_KNOWLEDGE_SYSTEM_PROMPT
    assert "разрешено дать отдельную справку из общих знаний" in service.requests[0][1]
    assert "не создавай вымышленные ссылки" in service.requests[0][1]


def test_rag_prompt_contains_language_guardrails_and_source_metadata():
    context = build_rag_context(
        [
            {
                "publication_title": "Тестовая публикация",
                "publication_id": 42,
                "chunk_id": 7,
                "chunk_index": 3,
                "similarity": 0.8765,
                "text": "Фрагмент публикации.",
            }
        ]
    )
    prompt = build_rag_prompt("Что найдено?", context)

    assert "ID публикации: 42" in context
    assert "ID фрагмента: 7" in context
    assert "Индекс фрагмента: 3" in context
    assert "Сходство: 0.876" in context
    assert "История диалога не является источником фактов" in build_rag_prompt(
        "Что найдено?", context, "Ассистент: старый ответ"
    )
    assert "Не дополняй ответ собственными знаниями" in prompt
    assert "Проверь все переданные источники" in prompt
    assert "Не используй китайский язык" in prompt
    assert "Не смешивай языки" in prompt
    assert "Вопрос пользователя:\nЧто найдено?" in prompt


def test_general_fallback_prompt_marks_general_knowledge_mode():
    prompt = build_general_fallback_prompt(
        "Что такое фотосинтез?",
        "Пользователь: Расскажи о растениях",
    )

    assert "не найдено подходящих фрагментов" in prompt
    assert "ответ из общих знаний" in prompt
    assert "Не повторяй уведомление" in prompt
    assert "Что такое фотосинтез?" in prompt


async def test_answer_without_sources_discloses_general_knowledge_and_has_no_sources(
    monkeypatch,
):
    class EmptyRepository:
        def __init__(self, _db) -> None:
            pass

        async def search_chunks(self, **_kwargs) -> list[dict]:
            return []

    class GeneralKnowledgeLLMService:
        async def generate_general_knowledge_answer(self, prompt: str) -> str:
            assert "ответ из общих знаний" in prompt
            return "Фотосинтез — процесс преобразования энергии света."

    monkeypatch.setattr(assistant, "SemanticSearchRepository", EmptyRepository)
    monkeypatch.setattr(assistant, "LocalLLMService", GeneralKnowledgeLLMService)

    result = await assistant._answer_question(
        question="Что такое фотосинтез?",
        limit=5,
        min_similarity=0.55,
        db=object(),
        embedding_service=StubEmbeddingService(),
    )

    assert result == {
        "question": "Что такое фотосинтез?",
        "answer": (
            "В текущих материалах я не нашёл информации для ответа на этот вопрос. "
            "Ниже — ответ из общих знаний, а не из загруженных публикаций.\n\n"
            "Фотосинтез — процесс преобразования энергии света."
        ),
        "sources": [],
    }


async def test_answer_returns_sources_with_exact_public_contract(monkeypatch):
    chunk = {
        "publication_id": 42,
        "publication_title": "Магматизм Сибири",
        "chunk_id": 7,
        "chunk_index": 3,
        "text": "Магматизм исследуемого региона имеет несколько этапов.",
        "similarity": 0.91,
    }

    class SourceRepository:
        def __init__(self, _db) -> None:
            pass

        async def search_chunks(self, **_kwargs) -> list[dict]:
            return [chunk]

    class AnsweringLLMService:
        async def generate_answer(self, _prompt: str) -> str:
            return "В публикации описано несколько этапов магматизма."

    monkeypatch.setattr(assistant, "SemanticSearchRepository", SourceRepository)
    monkeypatch.setattr(assistant, "LocalLLMService", AnsweringLLMService)

    result = await assistant._answer_question(
        question="Какие этапы имеет магматизм?",
        limit=5,
        min_similarity=0.55,
        db=object(),
        embedding_service=StubEmbeddingService(),
    )

    assert result["sources"] == [
        {
            "publication_id": 42,
            "publication_title": "Магматизм Сибири",
            "chunk_id": 7,
            "chunk_index": 3,
            "similarity": 0.91,
        }
    ]
    assert set(result["sources"][0]) == {
        "publication_id",
        "publication_title",
        "chunk_id",
        "chunk_index",
        "similarity",
    }
    assert AssistantAskResponse(**result).model_dump()["sources"] == result["sources"]


def test_answer_sources_are_unique_and_sorted_by_best_similarity():
    chunks = [
        {
            "publication_id": 1,
            "publication_title": "Первая статья",
            "chunk_id": 10,
            "chunk_index": 0,
            "similarity": 0.82,
        },
        {
            "publication_id": 2,
            "publication_title": "Вторая статья",
            "chunk_id": 20,
            "chunk_index": 0,
            "similarity": 0.94,
        },
        {
            "publication_id": 1,
            "publication_title": "Первая статья",
            "chunk_id": 11,
            "chunk_index": 1,
            "similarity": 0.91,
        },
        {
            "publication_id": 3,
            "publication_title": "Третья статья",
            "chunk_id": 30,
            "chunk_index": 0,
            "similarity": 0.75,
        },
    ]

    sources = assistant._build_answer_sources(chunks)

    assert [source["publication_id"] for source in sources] == [2, 1, 3]
    assert [source["similarity"] for source in sources] == [0.94, 0.91, 0.75]
    assert sources[1]["chunk_id"] == 11


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


def test_answer_source_selection_keeps_strong_semantic_supplements():
    direct_match = {
        "publication_id": 1,
        "publication_title": "Байкальская нерпа",
        "text": "Байкальская нерпа является эндемиком озера.",
        "similarity": 0.68,
    }
    semantic_match = {
        "publication_id": 2,
        "publication_title": "Эндемичные млекопитающие озера",
        "text": "В работе рассмотрена экология единственного пресноводного тюленя.",
        "similarity": 0.74,
    }

    assert select_answer_sources(
        "байкальские нерпы",
        [direct_match, semantic_match],
        limit=5,
    ) == [direct_match, semantic_match]


def test_answer_source_selection_prefers_different_publications():
    first_publication_best = {
        "publication_id": 1,
        "chunk_id": 10,
        "publication_title": "Первая публикация",
        "text": "Магматизм региона описан в первом фрагменте.",
        "similarity": 0.95,
    }
    first_publication_second = {
        "publication_id": 1,
        "chunk_id": 11,
        "publication_title": "Первая публикация",
        "text": "Магматизм региона описан во втором фрагменте.",
        "similarity": 0.94,
    }
    second_publication = {
        "publication_id": 2,
        "chunk_id": 20,
        "publication_title": "Вторая публикация",
        "text": "Магматизм региона сопоставлен с возрастом пород.",
        "similarity": 0.90,
    }
    third_publication = {
        "publication_id": 3,
        "chunk_id": 30,
        "publication_title": "Третья публикация",
        "text": "Магматизм региона связан с тектоническим этапом.",
        "similarity": 0.88,
    }
    chunks = [
        first_publication_best,
        first_publication_second,
        second_publication,
        third_publication,
    ]

    assert select_answer_sources("магматизм региона", chunks, limit=3) == [
        first_publication_best,
        second_publication,
        third_publication,
    ]


def test_source_diversification_fills_remaining_slots_with_extra_chunks():
    chunks = [
        {"publication_id": 1, "chunk_id": 10},
        {"publication_id": 1, "chunk_id": 11},
        {"publication_id": 2, "chunk_id": 20},
        {"publication_id": 2, "chunk_id": 21},
    ]

    selected = diversify_chunks_by_publication(chunks, limit=4)

    assert [chunk["chunk_id"] for chunk in selected] == [10, 20, 11, 21]
