import httpx
import pytest

from app.api import assistant
from app.schemas.assistant import AssistantAskResponse
from app.services import local_llm_service
from app.services.local_llm_service import (
    CHINESE_RE,
    GENERAL_KNOWLEDGE_SYSTEM_PROMPT,
    LocalLLMService,
    OllamaGenerationError,
    OllamaTimeoutError,
    OllamaUnavailableError,
    RAG_ANSWER_JSON_SCHEMA,
    RAG_SYSTEM_PROMPT,
    detect_question_language,
)
from app.services.prompt_builder import (
    build_general_fallback_prompt,
    build_rag_context,
    build_rag_prompt,
    clean_rag_chunk_text,
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
        self.response_formats: list[str | dict | None] = []

    async def _request_ollama(
        self,
        prompt: str,
        *,
        system_prompt: str,
        response_format: str | dict | None = None,
    ) -> str:
        self.requests.append((prompt, system_prompt))
        self.response_formats.append(response_format)
        return self.answers.pop(0)


class StubEmbeddingService:
    model_name = "fake-embedding-model"

    def embed_query(self, _text: str) -> list[float]:
        return [0.1, 0.2]

    def embed_text(self, _text: str) -> list[float]:
        return [0.1, 0.2]


class StubHTTPClient:
    def __init__(self, result) -> None:
        self.result = result

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return None

    async def post(self, *_args, **_kwargs):
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


@pytest.mark.parametrize(
    ("request_error", "expected_error"),
    [
        (httpx.ConnectError("offline"), OllamaUnavailableError),
        (httpx.ReadTimeout("slow"), OllamaTimeoutError),
    ],
)
async def test_ollama_request_maps_connection_failures(
    monkeypatch,
    request_error,
    expected_error,
):
    monkeypatch.setattr(
        local_llm_service.httpx,
        "AsyncClient",
        lambda **_kwargs: StubHTTPClient(request_error),
    )

    with pytest.raises(expected_error):
        await LocalLLMService()._request_ollama("Вопрос", system_prompt="Правила")


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(
            500,
            request=httpx.Request("POST", "http://ollama.test/api/chat"),
        ),
        httpx.Response(
            200,
            content=b"not-json",
            request=httpx.Request("POST", "http://ollama.test/api/chat"),
        ),
        httpx.Response(
            200,
            json={"message": {"content": "   "}},
            request=httpx.Request("POST", "http://ollama.test/api/chat"),
        ),
    ],
)
async def test_ollama_request_rejects_unusable_generation(monkeypatch, response):
    monkeypatch.setattr(
        local_llm_service.httpx,
        "AsyncClient",
        lambda **_kwargs: StubHTTPClient(response),
    )

    with pytest.raises(OllamaGenerationError):
        await LocalLLMService()._request_ollama("Вопрос", system_prompt="Правила")


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


async def test_generate_answer_never_returns_chinese_after_failed_retry():
    service = StubLLMService(
        [
            "Первый ответ содержит 中文.",
            "Повторный ответ всё ещё содержит 中文.",
        ]
    )

    answer = await service.generate_answer(
        "Вопрос пользователя",
        expected_language="ru",
    )

    assert answer == (
        "Не удалось сформировать корректный ответ на русском языке. "
        "Пожалуйста, повторите вопрос."
    )
    assert CHINESE_RE.search(answer) is None
    assert len(service.requests) == 2


def test_detect_question_language_uses_user_question_script():
    assert detect_question_language("Как сформировался Байкальский рифт?") == "ru"
    assert detect_question_language("How did the Baikal Rift form?") == "en"
    assert detect_question_language("Возраст Udzha paleorift?") == "ru"


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


async def test_generate_answer_uses_json_schema_for_structured_output():
    service = StubLLMService(
        ['{"blocks":[{"kind":"insufficient","text":"Нет данных.","source_ids":[]}]}']
    )

    await service.generate_answer(
        "Вопрос с найденными фрагментами",
        structured_output=True,
    )

    assert service.response_formats == [RAG_ANSWER_JSON_SCHEMA]


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
    assert "source_id: chunk-7" in context
    assert "Индекс фрагмента: 3" in context
    assert "Сходство: 0.876" in context
    assert "История диалога не является источником фактов" in build_rag_prompt(
        "Что найдено?", context, "Ассистент: старый ответ"
    )
    assert "Не дополняй ответ собственными знаниями" in prompt
    assert "Проверь все переданные источники" in prompt
    assert "самостоятельный человеческий ответ" in prompt
    assert "Не выводи в тексте ответа служебные данные" in prompt
    assert "без приветствия, вступления, повторения вопроса" in prompt
    assert "Не используй китайский язык" in prompt
    assert "Не смешивай языки" in prompt
    assert "Целевой уровень полноты ответа — не менее 80 %" in prompt
    assert "Не добивай объём повторами" in prompt
    assert "не добавляй список литературы" in prompt.lower()
    assert "смешаны кириллица и латиница" in prompt
    assert '"source_ids"' in prompt
    assert '"kind":"answer"' in prompt
    assert 'kind="insufficient"' in prompt
    assert "source_ids=[]" in prompt
    assert "Вопрос пользователя:\nЧто найдено?" in prompt

    plain_prompt = build_rag_prompt(
        "Что найдено?",
        context,
        structured_output=False,
    )
    assert "Верни только обычный текст без JSON" in plain_prompt
    assert '"blocks"' not in plain_prompt

    detailed_prompt = build_rag_prompt(
        "Что найдено?",
        context,
        detail_percent=95,
    )
    assert "Целевой уровень полноты ответа — не менее 95 %" in detailed_prompt


def test_rag_context_removes_trailing_further_reading_author_list():
    chunk_text = (
        "Геологическое строение включает ордовикские и силурийские отложения.\n"
        "Для более детального представления участков работ см. в следующих "
        "источниках: Гладкочуб и др., 2001; Ivanov et al., 2005; "
        "Gladкochуб и др., 2010."
    )

    cleaned = clean_rag_chunk_text(chunk_text)
    context = build_rag_context(
        [
            {
                "publication_title": "Геология участка",
                "publication_id": 42,
                "chunk_id": 7,
                "chunk_index": 3,
                "similarity": 0.9,
                "text": chunk_text,
            }
        ]
    )

    assert cleaned == (
        "Геологическое строение включает ордовикские и силурийские отложения."
    )
    assert cleaned in context
    assert "Ivanov et al." not in context
    assert "Gladкochуб" not in context
    assert "Ivanov et al." in build_rag_context(
        [
            {
                "publication_title": "Геология участка",
                "publication_id": 42,
                "chunk_id": 7,
                "chunk_index": 3,
                "similarity": 0.9,
                "text": chunk_text,
            }
        ],
        preserve_bibliography=True,
    )


def test_general_fallback_prompt_marks_general_knowledge_mode():
    prompt = build_general_fallback_prompt(
        "Что такое фотосинтез?",
        "Пользователь: Расскажи о растениях",
    )

    assert "не найдено подходящих фрагментов" in prompt
    assert "ответ из общих знаний" in prompt
    assert "Не повторяй уведомление" in prompt
    assert "Что такое фотосинтез?" in prompt


async def test_answer_without_relevant_sources_returns_insufficient_information(
    monkeypatch,
):
    irrelevant_chunk = {
        "publication_id": 42,
        "publication_title": "Палеогеография Сибирской платформы",
        "chunk_id": 7,
        "chunk_index": 3,
        "text": "Рассмотрены осадочные бассейны и тектонические структуры.",
        "similarity": 0.96,
    }

    class IrrelevantRepository:
        def __init__(self, _db) -> None:
            pass

        async def search_chunks(self, **_kwargs) -> list[dict]:
            return [irrelevant_chunk]

    class UnexpectedLLMService:
        def __init__(self) -> None:
            raise AssertionError("LLM не должна вызываться без релевантных фрагментов")

    monkeypatch.setattr(assistant, "SemanticSearchRepository", IrrelevantRepository)
    monkeypatch.setattr(assistant, "LocalLLMService", UnexpectedLLMService)

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
            "В текущих материалах недостаточно информации для ответа на этот вопрос. "
            "Уточните запрос или загрузите дополнительные публикации."
        ),
        "sources": [],
        "answer_blocks": [
            {
                "text": (
                    "В текущих материалах недостаточно информации для ответа на этот вопрос. "
                    "Уточните запрос или загрузите дополнительные публикации."
                ),
                "source_ids": [],
            }
        ],
        "answer_origin": "internal",
        "catalog": None,
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
        async def generate_answer(
            self,
            _prompt: str,
            *,
            expected_language: str,
            structured_output: bool,
        ) -> str:
            assert expected_language == "ru"
            assert structured_output is True
            return (
                '{"blocks":[{"kind":"answer","text":"Магматизм включает несколько '
                'этапов.","source_ids":["chunk-7"]}]}'
            )

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
            "source_id": "chunk-7",
            "publication_id": 42,
            "publication_title": "Магматизм Сибири",
            "chunk_id": 7,
            "chunk_index": 3,
            "similarity": 0.91,
        }
    ]
    assert set(result["sources"][0]) == {
        "source_id",
        "publication_id",
        "publication_title",
        "chunk_id",
        "chunk_index",
        "similarity",
    }
    assert result["answer_blocks"] == [
        {
            "text": "Магматизм включает несколько этапов.",
            "source_ids": ["chunk-7"],
        }
    ]
    assert result["answer_origin"] == "internal"
    assert AssistantAskResponse(**result).model_dump()["sources"] == result["sources"]


async def test_answer_retries_until_requested_source_coverage_is_reached(monkeypatch):
    chunks = [
        {
            "publication_id": 1,
            "publication_title": "Магматизм региона",
            "chunk_id": 10,
            "chunk_index": 0,
            "text": "Магматизм региона начался в раннем палеозое.",
            "similarity": 0.91,
        },
        {
            "publication_id": 2,
            "publication_title": "Магматические комплексы",
            "chunk_id": 20,
            "chunk_index": 1,
            "text": "Магматизм региона завершился формированием гранитов.",
            "similarity": 0.88,
        },
    ]

    class SourceRepository:
        def __init__(self, _db) -> None:
            pass

        async def search_chunks(self, **_kwargs) -> list[dict]:
            return chunks

    class AnsweringLLMService:
        def __init__(self) -> None:
            self.answers = [
                (
                    '{"blocks":[{"kind":"answer","text":"Магматизм начался '
                    'в раннем палеозое.","source_ids":["chunk-10"]}]}'
                ),
                (
                    '{"blocks":[{"kind":"answer","text":"Магматизм начался '
                    "в раннем палеозое и завершился формированием гранитов.",
                    '"source_ids":["chunk-10","chunk-20"]}]}'
                ),
            ]
            self.prompts: list[str] = []

        async def generate_answer(self, prompt: str, **_kwargs) -> str:
            self.prompts.append(prompt)
            return self.answers.pop(0)

    monkeypatch.setattr(assistant, "SemanticSearchRepository", SourceRepository)
    llm_service = AnsweringLLMService()
    monkeypatch.setattr(assistant, "LocalLLMService", lambda: llm_service)

    result = await assistant._answer_question(
        question="Когда начался магматизм региона?",
        limit=5,
        min_similarity=0.55,
        db=object(),
        embedding_service=StubEmbeddingService(),
    )

    assert [source["source_id"] for source in result["sources"]] == [
        "chunk-10",
        "chunk-20",
    ]
    assert len(llm_service.prompts) == 2
    assert "недостаточно релевантных источников" in llm_service.prompts[1]


async def test_answer_allows_insufficient_block_without_sources(monkeypatch):
    chunk = {
        "publication_id": 1,
        "publication_title": "Магматизм региона",
        "chunk_id": 10,
        "chunk_index": 0,
        "text": "Магматизм региона рассмотрен только в общих чертах.",
        "similarity": 0.91,
    }

    class SourceRepository:
        def __init__(self, _db) -> None:
            pass

        async def search_chunks(self, **_kwargs) -> list[dict]:
            return [chunk]

    class InsufficientLLMService:
        async def generate_answer(self, _prompt: str, **_kwargs) -> str:
            return (
                '{"blocks":[{"kind":"insufficient","text":"Для точного ответа '
                'недостаточно информации; уточните период.","source_ids":[]}]}'
            )

    monkeypatch.setattr(assistant, "SemanticSearchRepository", SourceRepository)
    monkeypatch.setattr(assistant, "LocalLLMService", InsufficientLLMService)

    result = await assistant._answer_question(
        question="В каком году начался магматизм региона?",
        limit=5,
        min_similarity=0.55,
        db=object(),
        embedding_service=StubEmbeddingService(),
    )

    assert result["answer_blocks"][0]["source_ids"] == []
    assert result["sources"] == []


async def test_answer_synthesizes_multiple_relevant_chunks(monkeypatch):
    chunks = [
        {
            "publication_id": 1,
            "publication_title": "Этапы магматизма",
            "chunk_id": 10,
            "chunk_index": 0,
            "text": "Ранний этап магматизма региона сформировал базальтовые комплексы.",
            "similarity": 0.92,
        },
        {
            "publication_id": 2,
            "publication_title": "Поздний магматизм",
            "chunk_id": 20,
            "chunk_index": 0,
            "text": "Поздний этап магматизма региона сопровождался внедрением гранитов.",
            "similarity": 0.89,
        },
    ]

    class SourceRepository:
        def __init__(self, _db) -> None:
            pass

        async def search_chunks(self, **_kwargs) -> list[dict]:
            return chunks

    class SynthesizingLLMService:
        async def generate_answer(self, prompt: str, **_kwargs) -> str:
            assert chunks[0]["text"] in prompt
            assert chunks[1]["text"] in prompt
            return (
                '{"blocks":[{"kind":"answer","text":"Магматизм включал ранний '
                'базальтовый и поздний гранитный этапы.",'
                '"source_ids":["chunk-10","chunk-20"]}]}'
            )

    monkeypatch.setattr(assistant, "SemanticSearchRepository", SourceRepository)
    monkeypatch.setattr(assistant, "LocalLLMService", SynthesizingLLMService)

    result = await assistant._answer_question(
        question="Какие этапы магматизма региона описаны?",
        limit=5,
        min_similarity=0.55,
        db=object(),
        embedding_service=StubEmbeddingService(),
    )

    assert result["answer"] == (
        "Магматизм включал ранний базальтовый и поздний гранитный этапы."
    )
    assert result["answer_blocks"][0]["source_ids"] == ["chunk-10", "chunk-20"]
    assert [source["source_id"] for source in result["sources"]] == [
        "chunk-10",
        "chunk-20",
    ]


async def test_russian_question_retries_noisy_answer_and_returns_clean_text(monkeypatch):
    chunk = {
        "publication_id": 1,
        "publication_title": "Возраст магматизма",
        "chunk_id": 10,
        "chunk_index": 0,
        "text": "Возраст магматизма региона составляет около 250 млн лет.",
        "similarity": 0.93,
    }

    class SourceRepository:
        def __init__(self, _db) -> None:
            pass

        async def search_chunks(self, **_kwargs) -> list[dict]:
            return [chunk]

    class RetryingLLMService:
        def __init__(self) -> None:
            self.answers = [
                (
                    '{"blocks":[{"kind":"answer","text":"The answer from '
                    'chunk-10 is 250.","source_ids":["chunk-10"]}]}'
                ),
                (
                    '{"blocks":[{"kind":"answer","text":"Возраст магматизма '
                    'региона составляет около 250 млн лет.",'
                    '"source_ids":["chunk-10"]}]}'
                ),
            ]
            self.prompts: list[str] = []

        async def generate_answer(
            self,
            prompt: str,
            *,
            expected_language: str,
            structured_output: bool,
        ) -> str:
            assert expected_language == "ru"
            assert structured_output is True
            self.prompts.append(prompt)
            return self.answers.pop(0)

    llm_service = RetryingLLMService()
    monkeypatch.setattr(assistant, "SemanticSearchRepository", SourceRepository)
    monkeypatch.setattr(assistant, "LocalLLMService", lambda: llm_service)

    result = await assistant._answer_question(
        question="Каков возраст магматизма региона?",
        limit=5,
        min_similarity=0.55,
        db=object(),
        embedding_service=StubEmbeddingService(),
    )

    assert result["answer"] == (
        "Возраст магматизма региона составляет около 250 млн лет."
    )
    assert len(llm_service.prompts) == 2
    assert "не прошёл проверку качества" in llm_service.prompts[1]


async def test_russian_answer_retries_mixed_ocr_name_and_unrequested_authors(
    monkeypatch,
):
    chunk = {
        "publication_id": 1,
        "publication_title": "Геологическое строение участка",
        "chunk_id": 10,
        "chunk_index": 0,
        "text": (
            "Территория сложена ордовикскими и силурийскими отложениями. "
            "Для более детального представления см. в следующих источниках: "
            "Ivanov et al., 2005; Gladкochуб и др., 2010."
        ),
        "similarity": 0.93,
    }

    class SourceRepository:
        def __init__(self, _db) -> None:
            pass

        async def search_chunks(self, **_kwargs) -> list[dict]:
            return [chunk]

    class RetryingLLMService:
        def __init__(self) -> None:
            self.answers = [
                (
                    '{"blocks":[{"kind":"answer","text":"Территория сложена '
                    'ордовикскими отложениями. Для деталей см. источники: '
                    'Ivanov et al., 2005; Gladкochуб и др., 2010.",'
                    '"source_ids":["chunk-10"]}]}'
                ),
                (
                    '{"blocks":[{"kind":"answer","text":"Территория сложена '
                    'ордовикскими и силурийскими отложениями.",'
                    '"source_ids":["chunk-10"]}]}'
                ),
            ]
            self.prompts: list[str] = []

        async def generate_answer(self, prompt: str, **_kwargs) -> str:
            self.prompts.append(prompt)
            return self.answers.pop(0)

    llm_service = RetryingLLMService()
    monkeypatch.setattr(assistant, "SemanticSearchRepository", SourceRepository)
    monkeypatch.setattr(assistant, "LocalLLMService", lambda: llm_service)

    result = await assistant._answer_question(
        question="Каково геологическое строение территории?",
        limit=5,
        min_similarity=0.55,
        db=object(),
        embedding_service=StubEmbeddingService(),
    )

    assert result["answer"] == (
        "Территория сложена ордовикскими и силурийскими отложениями."
    )
    assert len(llm_service.prompts) == 2
    assert "Ivanov et al." not in llm_service.prompts[0]
    assert "не перечисляй авторов или литературу" in llm_service.prompts[1]


async def test_answer_falls_back_to_plain_text_after_two_invalid_json_answers(
    monkeypatch,
):
    chunk = {
        "publication_id": 1,
        "publication_title": "Возраст магматизма",
        "chunk_id": 10,
        "chunk_index": 0,
        "text": "Возраст магматизма региона составляет около 250 млн лет.",
        "similarity": 0.93,
    }

    class SourceRepository:
        def __init__(self, _db) -> None:
            pass

        async def search_chunks(self, **_kwargs) -> list[dict]:
            return [chunk]

    class FallbackLLMService:
        def __init__(self) -> None:
            self.answers = [
                "Это не JSON.",
                "Снова не JSON.",
                "Возраст магматизма региона составляет около 250 млн лет.",
            ]
            self.structured_modes: list[bool] = []
            self.prompts: list[str] = []

        async def generate_answer(
            self,
            prompt: str,
            *,
            expected_language: str,
            structured_output: bool,
        ) -> str:
            assert expected_language == "ru"
            self.prompts.append(prompt)
            self.structured_modes.append(structured_output)
            return self.answers.pop(0)

    llm_service = FallbackLLMService()
    monkeypatch.setattr(assistant, "SemanticSearchRepository", SourceRepository)
    monkeypatch.setattr(assistant, "LocalLLMService", lambda: llm_service)

    result = await assistant._answer_question(
        question="Каков возраст магматизма региона?",
        limit=5,
        min_similarity=0.55,
        db=object(),
        embedding_service=StubEmbeddingService(),
    )

    assert result["answer"] == (
        "Возраст магматизма региона составляет около 250 млн лет."
    )
    assert result["sources"] == []
    assert result["answer_blocks"] == [
        {
            "text": "Возраст магматизма региона составляет около 250 млн лет.",
            "source_ids": [],
        }
    ]
    assert llm_service.structured_modes == [True, True, False]
    assert "Верни только обычный текст без JSON" in llm_service.prompts[2]


def test_answer_sources_are_unique_by_chunk_and_keep_multiple_publication_fragments():
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
        {
            "publication_id": 1,
            "publication_title": "Первая статья",
            "chunk_id": 11,
            "chunk_index": 1,
            "similarity": 0.87,
        },
    ]

    sources = assistant._build_answer_sources(chunks)

    assert [source["publication_id"] for source in sources] == [2, 1, 1, 3]
    assert [source["chunk_id"] for source in sources] == [20, 11, 10, 30]
    assert [source["source_id"] for source in sources] == [
        "chunk-20",
        "chunk-11",
        "chunk-10",
        "chunk-30",
    ]
    assert [source["similarity"] for source in sources] == [0.94, 0.91, 0.82, 0.75]


def test_relevance_filter_removes_semantically_near_but_unrelated_geology_sources():
    chunks = [
        {
            "publication_title": "Раннепротерозойские отложения юга Сибирского кратона",
            "text": "Фрагмент посвящен базитам, алмазоносным кимберлитовым трубкам и золотоносности.",
            "similarity": 0.66,
        }
    ]

    assert filter_relevant_sources("байкальские нерпы", chunks, limit=5) == []


def test_relevance_filter_rejects_high_similarity_irrelevant_figure_caption():
    chunks = [
        {
            "publication_title": "Формирование Байкальского рифта",
            "text": "Рис. 4. Схема расположения точек отбора проб.",
            "similarity": 0.97,
        }
    ]

    assert filter_relevant_sources(
        "Как формировался Байкальский рифт?",
        chunks,
        limit=5,
    ) == []


def test_relevance_filter_requires_all_meaningful_terms_for_short_queries():
    chunks = [
        {
            "publication_title": "Геология Байкальского региона",
            "text": "Фрагмент посвящен геологическим структурам и минерализации.",
            "similarity": 0.66,
        }
    ]

    assert filter_relevant_sources("байкальские нерпы", chunks, limit=5) == []


def test_relevance_filter_rejects_partial_short_query_without_direct_subject():
    chunks = [
        {
            "publication_title": "Исследования Байкала",
            "text": "Фрагмент описывает эндемичные виды озера и экологические наблюдения.",
            "similarity": 0.73,
        }
    ]

    assert filter_relevant_sources("байкальские нерпы", chunks, limit=5) == []


def test_relevance_filter_does_not_use_publication_title_as_chunk_evidence():
    chunks = [
        {
            "publication_title": "Герцинский Икатский надвиг в Забайкальском сегменте",
            "text": "Гистограмма возрастов детритовых цирконов из бластомилонита.",
            "similarity": 0.58,
        }
    ]

    assert filter_relevant_sources("герциниды", chunks, limit=5) == []


def test_relevance_filter_keeps_sources_with_question_terms():
    chunks = [
        {
            "publication_title": "Байкальская нерпа и озеро Байкал",
            "text": "Байкальская нерпа является эндемиком озера Байкал.",
            "similarity": 0.66,
        }
    ]

    assert filter_relevant_sources("байкальские нерпы", chunks, limit=5) == chunks


def test_answer_source_selection_does_not_fall_back_to_semantic_candidates():
    chunks = [
        {
            "publication_title": "Раннепротерозойские отложения юга Сибирского кратона",
            "text": "Фрагмент посвящен базитам, алмазоносным кимберлитовым трубкам и золотоносности.",
            "similarity": 0.66,
        }
    ]

    assert filter_relevant_sources("байкальские нерпы", chunks, limit=5) == []
    assert select_answer_sources("байкальские нерпы", chunks, limit=5) == []


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


def test_answer_source_selection_excludes_unverified_semantic_supplements():
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
    ) == [direct_match]


def test_answer_source_selection_requires_strict_evidence_for_every_source():
    same_language_noise = {
        "publication_id": 1,
        "publication_title": "Геохимические особенности минералов",
        "text": "Обсуждаются общие подходы к генетической классификации.",
        "similarity": 0.68,
    }
    cross_language_match = {
        "publication_id": 2,
        "publication_title": (
            "Apatite Geochemistry of the Slyudyanka Deposit: "
            "Multivariate Analysis for Genetic Classification"
        ),
        "text": "Trace element composition and the Y/Ho anomaly are analyzed.",
        "similarity": 0.66,
    }
    weak_cross_language_noise = {
        "publication_id": 3,
        "publication_title": "Unrelated mantle geodynamics",
        "text": "The paper discusses mantle evolution.",
        "similarity": 0.64,
    }

    assert select_answer_sources(
        (
            "Какие геохимические особенности апатита Слюдянского месторождения "
            "используются для генетической классификации?"
        ),
        [same_language_noise, cross_language_match, weak_cross_language_noise],
        limit=2,
    ) == []


def test_relevance_filter_keeps_high_confidence_generic_geology_answer():
    chunk = {
        "publication_title": "Геологическое строение участка",
        "text": "Территория сложена ордовикскими и силурийскими отложениями.",
        "similarity": 0.93,
    }

    assert filter_relevant_sources(
        "Каково геологическое строение территории?",
        [chunk],
        limit=5,
    ) == [chunk]


def test_relevance_filter_rejects_specific_question_with_only_generic_overlap():
    chunk = {
        "publication_title": "Возраст цирконов месторождения Северное",
        "text": "Территория месторождения расположена в пределах горного массива.",
        "similarity": 0.91,
    }

    assert filter_relevant_sources(
        "Каков возраст цирконов месторождения Северное?",
        [chunk],
        limit=5,
    ) == []


def test_relevance_filter_allows_only_clear_cross_language_semantic_winner():
    relevant = {
        "publication_title": "Apatite chemistry",
        "text": "U-Pb dating constrains apatite crystallization to 250 Ma.",
        "similarity": 0.86,
    }
    noise = {
        "publication_title": "Mantle evolution",
        "text": "The article discusses regional mantle evolution and deformation.",
        "similarity": 0.78,
    }

    assert filter_relevant_sources(
        "Каков возраст кристаллизации апатита?",
        [relevant, noise],
        limit=5,
    ) == [relevant]


def test_answer_source_selection_drops_candidates_far_below_best_match():
    best = {
        "publication_id": 1,
        "chunk_id": 10,
        "publication_title": "Возраст цирконов",
        "text": "Возраст цирконов месторождения составляет 250 млн лет.",
        "similarity": 0.91,
    }
    weak = {
        "publication_id": 2,
        "chunk_id": 20,
        "publication_title": "Другие датировки",
        "text": "Возраст цирконов месторождения обсуждается без численных данных.",
        "similarity": 0.72,
    }

    assert select_answer_sources(
        "Каков возраст цирконов месторождения?",
        [best, weak],
        limit=5,
    ) == [best]


def test_answer_source_selection_caps_context_at_three_strong_chunks():
    chunks = [
        {
            "publication_id": index,
            "chunk_id": index * 10,
            "publication_title": f"Магматизм региона {index}",
            "text": "Магматизм региона включал базальтовый этап.",
            "similarity": 0.94 - index * 0.01,
        }
        for index in range(1, 5)
    ]

    selected = select_answer_sources("магматизм региона", chunks, limit=5)

    assert len(selected) == 3
    assert selected == chunks[:3]


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
