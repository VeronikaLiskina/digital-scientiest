from app.services.pdf_import import (
    ExtractedPublicationMetadata,
    _dedupe_phrases,
    _extract_keywords,
    _extract_keywords_from_focused_text,
    _extract_topics_from_keywords,
    _filter_author_phrases,
    _format_phrase,
    _needs_ai_publication_analysis,
)


def _metadata(**overrides) -> ExtractedPublicationMetadata:
    values = {
        "title": "Reliable title",
        "year": 2025,
        "language": "en",
        "publication_type": "article",
        "doi": None,
        "authors": ["A. Author"],
        "keywords": ["geology"],
        "topics": ["Geology"],
        "title_source": "pdf",
        "title_confidence": "high",
        "title_warning": None,
    }
    values.update(overrides)
    return ExtractedPublicationMetadata(**values)


def test_ai_analysis_is_skipped_when_lightweight_metadata_is_complete():
    assert _needs_ai_publication_analysis(_metadata()) is False


def test_ai_analysis_is_used_as_fallback_for_incomplete_metadata():
    assert _needs_ai_publication_analysis(_metadata(authors=[])) is True
    assert _needs_ai_publication_analysis(_metadata(keywords=[])) is True
    assert _needs_ai_publication_analysis(_metadata(year=None)) is True
    assert _needs_ai_publication_analysis(
        _metadata(title_source="filename", title_confidence="medium")
    ) is True


def test_explicit_keywords_are_cleaned_and_normalized():
    text = """
    Вестник геологии и геофизики
    Ключевые слова: витимского метеороида; снегового покрова; абляционного следа;
    академии наук; Институт земной коры; DOI 10.1234/test
    Аннотация. Рассмотрены природные явления.
    """

    assert _extract_keywords(text) == [
        "Витимский метеороид",
        "Снеговой покров",
        "Абляционный след",
    ]


def test_fallback_keywords_use_title_and_abstract_not_service_blocks():
    title = "Вещество абляционного следа Витимского метеороида в снеговом покрове"
    text = f"""
    {title}
    Аннотация. В работе изучены вещество абляционного следа, Витимский метеороид
    и снеговой покров в районе падения. Полученные данные исследования обсуждаются.
    Таблица 1. Химический состав образцов
    Список литературы
    Иванов И.И. Институт земной коры СО РАН. 2020.
    """

    keywords = _extract_keywords_from_focused_text(text, title=title, language="ru")

    assert "Абляционный след" in keywords
    assert "Витимский метеороид" in keywords
    assert "Снеговой покров" in keywords
    assert "Институт земной коры" not in keywords
    assert "Данные исследования" not in keywords


def test_topics_are_broad_limited_and_do_not_copy_all_keywords():
    topics = _extract_topics_from_keywords(
        title="Раннепалеозойский высококалиевый магматизм Сибирского кратона",
        keywords=[
            "Высококалиевый магматизм",
            "Чекуровская антиклиналь",
            "Сибирский кратон",
            "Детритовые цирконы",
            "LA-ICP-MS",
        ],
    )

    assert {"Магматизм", "Геохронология", "Сибирский кратон"}.issubset(set(topics))
    assert len(topics) <= 5
    assert "Чекуровская антиклиналь" not in topics
    assert "Высококалиевый магматизм" not in topics


def test_phrase_filter_rejects_metadata_garbage():
    assert _dedupe_phrases(
        [
            "Академии наук",
            "Институт земной коры",
            "Геодинамическая эволюция литосферы",
            "Результаты анализа",
            "Сибирский кратон",
        ]
    ) == ["Сибирский кратон"]


def test_russian_phrase_normalization_is_conservative():
    assert _format_phrase("витимского метеороида", language="ru") == "Витимский метеороид"
    assert _format_phrase("снегового покрова", language="ru") == "Снеговой покров"
    assert _format_phrase("абляционного следа", language="ru") == "Абляционный след"
    assert _format_phrase("вещество абляционного следа", language="ru") == "Вещество абляционного следа"
    assert _format_phrase("верхнемантийных плюмы", language="ru") == "Верхнемантийные плюмы"
    assert (
        _format_phrase("кайнозойских верхнемантийных плюмы", language="ru")
        == "Кайнозойские верхнемантийные плюмы"
    )
    assert _format_phrase("восточная сибирь", language="ru") == "Восточная Сибирь"
    assert _format_phrase("центральной монголия", language="ru") == "Центральная Монголия"


def test_incomplete_russian_keyword_phrases_are_rejected():
    values = [
        _format_phrase("Природа кайнозойских", language="ru"),
        _format_phrase("кайнозойских верхнемантийных", language="ru"),
        _format_phrase("верхнемантийных плюмы", language="ru"),
        _format_phrase("Плюмы восточной", language="ru"),
        _format_phrase("Восточная сибирь", language="ru"),
        _format_phrase("Сибири россия", language="ru"),
        _format_phrase("Кайнозойских верхнемантийных плюмы", language="ru"),
        _format_phrase("Центральной монголия", language="ru"),
        _format_phrase("Частей плюмы", language="ru"),
        _format_phrase("Млн годы", language="ru"),
    ]

    assert _dedupe_phrases(values) == [
        "Верхнемантийные плюмы",
        "Восточная Сибирь",
        "Кайнозойские верхнемантийные плюмы",
        "Центральная Монголия",
    ]


def test_author_names_are_removed_from_keyword_suggestions():
    keywords = _filter_author_phrases(
        [
            "gakkel ridge",
            "ivan koulakov",
            "koulakov mingqi",
            "andrey jakovlev aleksey",
            "seismic tomography",
        ],
        [
            "Ivan Koulakov",
            "Mingqi Liu",
            "Andrey Jakovlev",
            "Aleksey Ivanov",
        ],
    )

    assert keywords == ["gakkel ridge", "seismic tomography"]
