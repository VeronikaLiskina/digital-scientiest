import pytest

from app.services.publication_search_service import PublicationSearch, parse_publication_search


@pytest.fixture(autouse=True)
async def prepare_test_database():
    yield


@pytest.mark.parametrize(("question", "expected"), [
    ("какие публикации есть по магнитизму", PublicationSearch(topic="магнитизму")),
    ("Покажи все статьи о ботанике", PublicationSearch(topic="ботанике")),
    ("Какие статьи посвящены Байкалу?", PublicationSearch(topic="байкалу")),
    ("В каких публикациях упоминается циркон?", PublicationSearch(topic="циркон")),
    ("Подбери публикации по геологии за 2020–2024 годы", PublicationSearch(topic="геологии", year_from=2020, year_to=2024)),
    ("Найди публикации автора Иванова за 2023 год", PublicationSearch(author="иванова", year_from=2023, year_to=2023)),
    ("Подбери статьи по автору Иванову", PublicationSearch(author="иванову")),
    ("Покажи статьи по магнитизму автора Иванова на русском за 2023 год", PublicationSearch(topic="магнитизму", author="иванова", language="ru", year_from=2023, year_to=2023)),
    ("Публикации после 2020 года", PublicationSearch(year_from=2021)),
    ("Покажи публикации до 2020 года", PublicationSearch(year_to=2019)),
    ("Найди публикации с 2020 по 2024 год", PublicationSearch(year_from=2020, year_to=2024)),
    ("Покажи обзоры на английском языке", PublicationSearch(publication_type="review", language="en")),
    ("Покажи публикации типа статья", PublicationSearch(publication_type="article")),
    ("Покажи материалы конференции", PublicationSearch(publication_type="conference")),
    ("Покажи отчёты", PublicationSearch(publication_type="report")),
    ("Подбери книги", PublicationSearch(publication_type="book")),
    ("Покажи публикации типа тезисы", PublicationSearch(publication_type="thesis")),
    ("Сколько статей о базальтах?", PublicationSearch(topic="базальтах", count_only=True)),
    ("Покажи публикации с ключевым словом циркон", PublicationSearch(topic="циркон")),
    ("Покажи статьи по ботанике с описанием", PublicationSearch(topic="ботанике", with_descriptions=True)),
    ("Можешь подобрать мне статьи по магнитизму?", PublicationSearch(topic="магнитизму")),
    ("Покажи, пожалуйста, публикации по цирконам", PublicationSearch(topic="цирконам")),
    ("Find publications about paleomagnetism", PublicationSearch(topic="paleomagnetism")),
    ("Could you show me papers on geology from 2020 to 2024 in English?", PublicationSearch(topic="geology", year_from=2020, year_to=2024, language="en")),
    ("How many papers by Ivanov since 2020?", PublicationSearch(author="ivanov", year_from=2020, count_only=True)),
    ("Покажи статьи Диденко", PublicationSearch(author="диденко")),
])
def test_parse_catalog_criteria(question, expected):
    assert parse_publication_search(question) == expected


@pytest.mark.parametrize("question", [
    "Какие методы описаны в статьях?", "Как возникает магнитизм?",
    "Сравни результаты публикаций по ботанике", "Какие статьи есть?",
    "Покажи публикации с неизвестным условием",
    "Покажи статьи Байкал", "Объясни, какие статьи по магнитизму цитируются в тексте",
])
def test_scientific_and_unfiltered_questions_keep_existing_routes(question):
    assert parse_publication_search(question) is None


def test_description_followup_keeps_filters():
    assert parse_publication_search(
        "А о чём они?", "Пользователь: Подбери статьи по ботанике за 2023 год\nАссистент: Найдено 2."
    ) == PublicationSearch(topic="ботанике", year_from=2023, year_to=2023, with_descriptions=True)


@pytest.mark.parametrize(("question", "expected"), [
    ("А только до 2010 года?", PublicationSearch(topic="магнитизму", year_to=2009)),
    ("А на английском?", PublicationSearch(topic="магнитизму", language="en")),
    ("Сколько их?", PublicationSearch(topic="магнитизму", count_only=True)),
])
def test_filter_followup_keeps_topic(question, expected):
    assert parse_publication_search(question, "Пользователь: Покажи публикации по магнитизму") == expected


def test_multiple_followups_preserve_accumulated_filters():
    conversation = "Пользователь: Покажи статьи по ботанике\nПользователь: А только с 2020 года?\nПользователь: А на русском?"
    assert parse_publication_search("А о чем они?", conversation) == PublicationSearch(
        topic="ботанике", year_from=2020, language="ru", with_descriptions=True,
    )


def test_filter_followup_does_not_reuse_unrelated_scientific_question():
    assert parse_publication_search("А только до 2010 года?", "Пользователь: Что такое магнитизм?") is None


@pytest.mark.parametrize(("question", "expected"), [
    ("Найди работы с участием Huaiyu He.", PublicationSearch(author="huaiyu he")),
    ("Есть ли в базе публикации за 2026 год?", PublicationSearch(year_from=2026, year_to=2026)),
    ("Есть ли в базе данных публикации за 2035 год?", PublicationSearch(year_from=2035, year_to=2035)),
])
def test_participation_and_database_existence_requests(question, expected):
    assert parse_publication_search(question) == expected


def test_joint_authors_are_separate_required_conditions():
    filters = parse_publication_search("Какие публикации написаны совместно Ивановым А.В. и Демонтеровой Е.И.?")
    assert filters is not None
    assert filters.author == ""
    assert filters.authors == ("ивановым а.в.", "демонтеровой е.и.")


def test_language_adjective_before_document_noun():
    assert parse_publication_search("Покажи англоязычные статьи о Сибирских траппах за 2005–2015 годы.") == PublicationSearch(
        topic="сибирских траппах", language="en", year_from=2005, year_to=2015)


def test_followup_refines_previous_selection_with_language_and_years():
    assert parse_publication_search("Оставь из них только англоязычные работы за 2009–2015 годы.",
        "Пользователь: Найди публикации по Сибирским траппам.") == PublicationSearch(
            topic="сибирским траппам", language="en", year_from=2009, year_to=2015)


def test_language_followup_preserves_requested_document_type():
    assert parse_publication_search("А только англоязычные обзоры?",
        "Пользователь: Покажи публикации по ботанике") == PublicationSearch(
            topic="ботанике", language="en", publication_type="review")
