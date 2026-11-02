from collections import OrderedDict
from threading import Lock
from concurrent.futures import ThreadPoolExecutor

import pytest

from app.services.assistant_answer_service import parse_structured_rag_answer
from app.services.assistant_chat_service import contextual_search_question
from app.services.assistant_retrieval_service import AssistantRetrievalService
from app.services.llm.base import LLMGenerationError
from app.services.reranker_service import RerankerError, RerankerService
from scripts.evaluate_assistant import check_response


@pytest.fixture(autouse=True)
async def prepare_test_database():
    yield


async def test_repeated_search_translation_does_not_repeat_model_request(monkeypatch):
    from app.api import assistant

    translations = []

    class Translator:
        async def translate_search_query(self, question, *, source_language):
            translations.append((question, source_language))
            return "How old is the Baikal rift?"

    monkeypatch.setattr(assistant, "LocalLLMService", Translator)
    question = "Каков возраст Байкальского рифта?"
    first = await assistant._translate_search_query(question, source_language="ru")
    second = await assistant._translate_search_query(question, source_language="ru")

    assert first == second == "How old is the Baikal rift?"
    assert len(translations) == 1


async def test_search_translation_expires_and_is_separate_for_models_and_languages(monkeypatch):
    from app.api import assistant
    from app.core.config import settings

    calls = []

    class Translator:
        async def translate_search_query(self, question, *, source_language):
            calls.append((question, source_language))
            return "Translated search query"

    monkeypatch.setattr(assistant, "_translation_cache", OrderedDict())
    monkeypatch.setattr(assistant, "LocalLLMService", Translator)
    monkeypatch.setattr(assistant, "TRANSLATION_CACHE_TTL_SECONDS", -1)
    await assistant._translate_search_query("original question", source_language="ru")
    await assistant._translate_search_query("original question", source_language="ru")
    assert len(calls) == 2

    monkeypatch.setattr(assistant, "TRANSLATION_CACHE_TTL_SECONDS", 600)
    await assistant._translate_search_query("original question", source_language="ru")
    await assistant._translate_search_query("original question", source_language="en")
    monkeypatch.setattr(settings, "llm_provider", "api")
    monkeypatch.setattr(settings, "llm_api_model", "another-model")
    await assistant._translate_search_query("original question", source_language="ru")
    assert len(calls) == 5


async def test_translation_failure_and_empty_result_are_not_cached(monkeypatch):
    from app.api import assistant
    from app.services.llm.base import LLMUnavailableError

    outputs = [LLMUnavailableError("offline"), "", "A valid translation"]

    class Translator:
        async def translate_search_query(self, *_args, **_kwargs):
            value = outputs.pop(0)
            if isinstance(value, Exception):
                raise value
            return value

    monkeypatch.setattr(assistant, "_translation_cache", OrderedDict())
    monkeypatch.setattr(assistant, "LocalLLMService", Translator)
    with pytest.raises(LLMUnavailableError):
        await assistant._translate_search_query("original", source_language="ru")
    assert await assistant._translate_search_query("original", source_language="ru") == ""
    assert await assistant._translate_search_query("original", source_language="ru") == "A valid translation"
    assert await assistant._translate_search_query("original", source_language="ru") == "A valid translation"


async def test_translation_cache_has_a_fixed_size(monkeypatch):
    from app.api import assistant

    class Translator:
        async def translate_search_query(self, question, **_kwargs):
            return f"Translated {question}"

    monkeypatch.setattr(assistant, "_translation_cache", OrderedDict())
    monkeypatch.setattr(assistant, "LocalLLMService", Translator)
    monkeypatch.setattr(assistant, "TRANSLATION_CACHE_MAX_ENTRIES", 2)
    for question in ("first", "second", "third"):
        await assistant._translate_search_query(question, source_language="ru")
    assert len(assistant._translation_cache) == 2
    assert all(key[-1] != "first" for key in assistant._translation_cache)


def test_scientific_followup_search_includes_user_context_without_reusing_answer_facts():
    conversation = "Пользователь: Каков возраст Малого Мурунского массива?\nАссистент: Непроверенное утверждение."
    query = contextual_search_question("А какие минералы там известны?", conversation)
    assert "Мурунского" in query
    assert "минералы" in query
    assert "Непроверенное" not in query


def test_standalone_scientific_question_does_not_inherit_unrelated_context():
    question = "Как датировали цирконы Азейского месторождения?"
    assert contextual_search_question(question, "Пользователь: Что такое магматизм?") == question


def cached_scorer(scorer, capacity=2):
    service = RerankerService.__new__(RerankerService)
    service._score_cache = OrderedDict()
    service._score_cache_lock = Lock()
    service._score_cache_size = capacity
    service._score_uncached_pairs = scorer
    return service


def test_reranker_cache_reuses_identical_pairs_but_scores_new_and_edited_text():
    calls = []

    def score(pairs):
        calls.extend(pairs)
        return [len(passage) / 100 for _, passage in pairs]

    service = cached_scorer(score)
    assert service._score_pairs([("Q", "first"), ("Q", "second"), ("Q", "first")]) == [0.05, 0.06, 0.05]
    assert len(calls) == 2
    assert service._score_pairs([("Q", "first"), ("Q", "edited")]) == [0.05, 0.06]
    assert len(calls) == 3
    assert len(service._score_cache) == 2
    service._score_pairs([("another question", "first")])
    assert len(calls) == 4


def test_reranker_cache_never_keeps_invalid_scores():
    service = cached_scorer(lambda pairs: [float("nan")])
    with pytest.raises(RerankerError):
        service._score_pairs([("Q", "text")])
    assert not service._score_cache


def test_concurrent_cold_requests_load_one_embedding_model(monkeypatch):
    from app import dependencies

    calls = []

    def load(*args, **kwargs):
        instance = object()
        calls.append(instance)
        return instance

    dependencies._load_embedding_service.cache_clear()
    monkeypatch.setattr(dependencies, "EmbeddingService", load)
    try:
        with ThreadPoolExecutor(max_workers=4) as pool:
            instances = list(pool.map(lambda _: dependencies.get_embedding_service(), range(8)))
        assert len(calls) == 1
        assert all(instance is instances[0] for instance in instances)
    finally:
        dependencies._load_embedding_service.cache_clear()


@pytest.mark.parametrize("raw", [
    '{"blocks":[{"kind":[],"text":"text","source_ids":[]}]}',
    '{"blocks":[{"kind":"answer","text":"text","source_ids":[{}]}]}',
])
def test_malformed_structured_answers_raise_recoverable_model_error(raw):
    with pytest.raises(LLMGenerationError):
        parse_structured_rag_answer(raw, allowed_source_ids={"chunk-1"})


def test_evaluator_rejects_numbers_without_expected_citations():
    failures = check_response(
        {"origin": "internal", "source_publications": [48], "answer_patterns": ["137", "128"]},
        {"answer_origin": "internal", "answer": "137–128 Ma", "sources": [], "answer_blocks": []},
    )
    assert "expected publication missing from answer citations" in failures


def test_evaluator_rejects_out_of_scope_publications_in_followups():
    failures = check_response(
        {"origin": "catalog", "year_to": 2010},
        {"answer_origin": "catalog", "answer": "Found", "catalog": {
            "items": [{"publication_id": 1, "year": 2024}],
        }},
    )
    assert failures == ["publication outside upper year boundary"]


async def test_bilingual_search_runs_after_initial_matches_fail_reranking():
    original = [{"chunk_id": n, "publication_id": n, "similarity": .82, "text": "noise"} for n in (1, 2)]
    evidence = {"chunk_id": 3, "publication_id": 21, "similarity": .88, "text": "80 apatite samples"}
    queries = []

    class Repository:
        async def search_chunks(self, **kwargs):
            queries.append(kwargs["query_text"])
            return [evidence] if kwargs["query_text"] == "translated" else original

    class Embeddings:
        model_name = "test"

        def embed_query(self, query):
            return [0.1]

    class Reranker:
        def rerank(self, question, chunks, *, limit):
            return [{**evidence, "reranker_score": .95}] if question == "translated" else []

    translations = []

    async def translate(question, *, source_language):
        translations.append(question)
        return "translated"

    service = AssistantRetrievalService(repository=Repository(), embedding_service=Embeddings(),
        reranker_factory=Reranker, query_translator=translate)
    service._apply_relevance_gate = lambda question, chunks, **kwargs: chunks
    result = await service.retrieve(question="original", source_language="ru", limit=5, min_similarity=.55)
    assert queries == ["original", "translated"]
    assert translations == ["original"]
    assert [row["chunk_id"] for row in result] == [3]


async def test_foreign_language_evidence_is_verified_even_with_two_initial_matches():
    from app.services.source_relevance import is_cross_language_pair

    assert is_cross_language_pair("Каков возраст Мурунского массива?", "The Malyy Murun igneous complex is 137 to 128 million years old.")
    translations = []

    class Repository:
        async def search_chunks(self, **kwargs):
            return [
                {"chunk_id": 1, "publication_id": 1, "similarity": .88, "text": "The Malyy Murun igneous complex is 137 to 128 million years old."},
                {"chunk_id": 2, "publication_id": 2, "similarity": .85, "text": "Изучены возраст и геохронология других массивов."},
            ]

    class Embeddings:
        model_name = "test"

        def embed_query(self, query):
            return [0.1]

    class Reranker:
        def rerank(self, question, chunks, *, limit):
            assert question == "translated"
            return [{**chunks[0], "reranker_score": .95}]

    async def translate(question, *, source_language):
        translations.append(question)
        return "translated"

    service = AssistantRetrievalService(repository=Repository(), embedding_service=Embeddings(),
        reranker_factory=Reranker, query_translator=translate)
    service._apply_relevance_gate = lambda question, chunks, **kwargs: chunks
    result = await service.retrieve(question="Каков возраст Мурунского массива?", source_language="ru", limit=5, min_similarity=.55)
    assert len(translations) == 1
    assert result[0]["chunk_id"] == 1
