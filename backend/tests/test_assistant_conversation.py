import json

import pytest

from app.api import assistant
from app.services import assistant_conversation_service as general
from app.services.assistant_answer_service import single_answer_block


@pytest.fixture(autouse=True)
async def prepare_test_database():
    yield


@pytest.mark.parametrize("question", ["Привет!", "Привет, как дела?", "Добрый день", "Спасибо", "Что ты умеешь?", "Давай поговорим о музыке", "Расскажи анекдот", "Как приготовить омлет?", "Hello!", "Hi, how are you?", "Tell me a joke"])
def test_smalltalk_and_explicit_general_tasks(question):
    assert general.is_general_conversation(question)


@pytest.mark.parametrize("question", ["Какие методы описаны в загруженных статьях?", "Какая урожайность в 2050 году указана в загруженных публикациях?", "Согласно статье, какой возраст массива?", "Что утверждает автор этой статьи?", "What methods are used in the uploaded papers?"])
def test_explicit_archive_requests_require_evidence(question):
    assert general.requires_publication_evidence(question)


def test_greeting_with_scientific_question_is_not_mistaken_for_smalltalk():
    assert not general.is_general_conversation("Привет! Каков возраст Малого Мурунского массива?")


def test_followup_to_general_answer_uses_conversational_branch():
    assert general.is_general_conversation("А почему именно так?", previous_origin="external")
    assert not general.is_general_conversation("А почему именно так?", previous_origin="internal")


def setup(monkeypatch, *, chunks=None, insufficient=False):
    calls = []

    async def no_catalog(**kwargs):
        return None

    class LLM:
        async def generate_general_knowledge_answer(self, prompt, **kwargs):
            calls.append(prompt)
            return "Привет! Можем поговорить о музыке, программировании или науке."

    class Retrieval:
        def __init__(self, **kwargs):
            pass

        async def retrieve(self, **kwargs):
            return chunks or []

    monkeypatch.setattr(assistant, "_answer_database_question", no_catalog)
    monkeypatch.setattr(general, "LocalLLMService", LLM)
    monkeypatch.setattr(assistant, "get_embedding_service", lambda: object())
    monkeypatch.setattr(assistant, "AssistantRetrievalService", Retrieval)
    return calls


def forbid_search(monkeypatch):
    def fail(*args, **kwargs):
        pytest.fail("General conversation must not load archive models")

    monkeypatch.setattr(assistant, "get_embedding_service", fail)
    monkeypatch.setattr(assistant, "get_reranker_service", fail)
    monkeypatch.setattr(assistant, "SemanticSearchRepository", fail)


async def ask(question, **kwargs):
    return await assistant._answer_question(question=question, db=object(), limit=5, min_similarity=.55, **kwargs)


@pytest.mark.parametrize(("question", "options"), [
    ("Привет", {}),
    ("Объясни рекурсию", {"mode": "general"}),
    ("А почему именно так?", {"previous_origin": "external"}),
])
async def test_general_branches_do_not_load_models_or_search(monkeypatch, question, options):
    calls = setup(monkeypatch)
    forbid_search(monkeypatch)
    result = await ask(question, **options)
    assert result["answer_origin"] == "external"
    assert result["sources"] == []
    assert result["catalog"] is None
    assert result["answer_blocks"] == single_answer_block(result["answer"])
    assert len(calls) == 1
    assert "не найдено подходящих фрагментов" not in calls[0]


async def test_auto_falls_back_to_general_knowledge_when_no_evidence(monkeypatch):
    calls = setup(monkeypatch)
    result = await ask("Что такое фотосинтез?")
    assert result["answer_origin"] == "external"
    assert "не найдено подходящих фрагментов" in calls[0]


@pytest.mark.parametrize(("question", "options"), [
    ("Каков возраст массива?", {"mode": "publications"}),
    ("Какая урожайность в 2050 году указана в загруженных публикациях?", {}),
])
async def test_archive_requests_do_not_turn_missing_evidence_into_general_facts(monkeypatch, question, options):
    calls = setup(monkeypatch)
    result = await ask(question, **options)
    assert result["answer_origin"] == "internal"
    assert "недостаточно" in result["answer"]
    assert not calls


async def test_auto_also_falls_back_after_llm_reports_insufficient_evidence(monkeypatch):
    chunk = {"chunk_id": 1, "publication_id": 1, "publication_title": "Title", "chunk_index": 0, "similarity": .9, "text": "Sparse evidence"}
    calls = setup(monkeypatch, chunks=[chunk])

    class InsufficientLLM:
        async def generate_answer(self, *args, **kwargs):
            return json.dumps({"blocks": [{"kind": "insufficient", "text": "Недостаточно информации для ответа.", "source_ids": []}]})

    monkeypatch.setattr(assistant, "LocalLLMService", InsufficientLLM)
    result = await ask("Почему небо голубое?")
    assert result["answer_origin"] == "external"
    assert len(calls) == 1


async def test_general_prompt_includes_chat_history(monkeypatch):
    calls = setup(monkeypatch)
    forbid_search(monkeypatch)
    await ask("Придумай ещё пример", mode="general", conversation="Пользователь: Мне интересны кошки\nАссистент: Обсуждали кошек.")
    assert "Мне интересны кошки" in calls[0]
