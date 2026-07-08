from app.services.pdf_import import PageText
from app.services.pdf_import import TitleMatch
from app.services.pdf_import import _extract_authors
from app.services.pdf_import import format_author_display_name


def test_extracts_authors_only_from_lines_after_title():
    pages = [
        PageText(
            number=0,
            text=(
                "Результаты датирования цирконов\n"
                "Иванов И.И., Петров П.П.\n"
                "Иркутский государственный университет\n"
                "Аннотация\n"
                "Текст статьи."
            ),
            lines=[
                "Результаты датирования цирконов",
                "Иванов И.И., Петров П.П.",
                "Иркутский государственный университет",
                "Аннотация",
                "Текст статьи.",
            ],
        )
    ]

    authors = _extract_authors(
        pages,
        title_match=TitleMatch(
            title="Результаты датирования цирконов",
            page_index=0,
            line_index=0,
            score=9,
        ),
        kind="generic_article",
    )

    assert authors == ["Иванов И.И.", "Петров П.П."]


def test_does_not_use_contents_or_neighbor_articles_as_author_fallback():
    pages = [
        PageText(
            number=0,
            text=(
                "Содержание\n"
                "Результаты датирования цирконов Иванов И.И.\n"
                "Использование состава долеритов Петров П.П.\n"
                "Аннотация"
            ),
            lines=[
                "Содержание",
                "Результаты датирования цирконов Иванов И.И.",
                "Использование состава долеритов Петров П.П.",
                "Аннотация",
            ],
        )
    ]

    authors = _extract_authors(
        pages,
        title_match=TitleMatch(
            title="Результаты датирования цирконов",
            page_index=0,
            line_index=None,
            score=8,
        ),
        kind="conference_collection",
    )

    assert authors == []


def test_stops_author_zone_at_references():
    pages = [
        PageText(
            number=0,
            text=(
                "Real Article Title About Zircon Dating\n"
                "References\n"
                "Ivanov A. V. Neighbor article title. Journal, 2020."
            ),
            lines=[
                "Real Article Title About Zircon Dating",
                "References",
                "Ivanov A. V. Neighbor article title. Journal, 2020.",
            ],
        )
    ]

    authors = _extract_authors(
        pages,
        title_match=TitleMatch(
            title="Real Article Title About Zircon Dating",
            page_index=0,
            line_index=0,
            score=9,
        ),
        kind="generic_article",
    )

    assert authors == []


def test_author_normalization_variants_share_canonical_format():
    assert format_author_display_name("Иванов А.В.") == "Иванов А.В."
    assert format_author_display_name("Иванов А. В.") == "Иванов А.В."
    assert format_author_display_name("А. В. Иванов") == "Иванов А.В."
    assert format_author_display_name("Ivanov A. V.") == "Иванов А.В."
    assert format_author_display_name("Alexei Ivanov") == "Alexei Ivanov"


def test_author_normalization_handles_initials_without_dots():
    assert format_author_display_name("Smith A B") == "Smith А.Б."
    assert format_author_display_name("A B Smith") == "Smith А.Б."


def test_extracts_latin_full_names_with_affiliation_numbers():
    pages = [
        PageText(
            number=0,
            text=(
                "Reply to: Increase of P-wave velocity due to\n"
                "melt in the mantle at the Gakkel Ridge\n"
                "Ivan Koulakov 1,2 ,V e r aS c h l i n d w e i n3,4, Mingqi Liu 5, Taras Gerya 5\n"
                "Andrey Jakovlev 1 & Aleksey Ivanov 2\n"
                "REPLYING TO Z. Yu & S. C. Singh Nature Communications"
            ),
            lines=[
                "Reply to: Increase of P-wave velocity due to",
                "melt in the mantle at the Gakkel Ridge",
                "Ivan Koulakov 1,2 ,V e r aS c h l i n d w e i n3,4, Mingqi Liu 5, Taras Gerya 5",
                "Andrey Jakovlev 1 & Aleksey Ivanov 2",
                "REPLYING TO Z. Yu & S. C. Singh Nature Communications",
            ],
        )
    ]

    authors = _extract_authors(
        pages,
        title_match=TitleMatch(
            title="Reply to: Increase of P-wave velocity due to melt in the mantle at the Gakkel Ridge",
            page_index=0,
            line_index=0,
            score=9,
        ),
        kind="generic_article",
    )

    assert authors == [
        "Ivan Koulakov",
        "Vera Schlindwein",
        "Mingqi Liu",
        "Taras Gerya",
        "Andrey Jakovlev",
        "Aleksey Ivanov",
    ]


def test_does_not_extract_affiliation_name_in_university_phrase():
    pages = [
        PageText(
            number=0,
            text=(
                "СВИДЕТЕЛЬСТВА КРАТКИХ ИНТЕНСИВНЫХ ПИКОВ\n"
                "МАГМАТИЧЕСКОЙ АКТИВНОСТИ НА ЮГЕ СИБИРСКОЙ ПЛАТФОРМЫ\n"
                "© 2013 г. А. В. Латышев1,2, Р. В. Веселовский1,2, А. В. Иванов3,\n"
                "А. М. Фетисова1, В. Э. Павлов2\n"
                "Московский государственный университет имени М.В. Ломоносова, геологический факультет, г. Москва\n"
                "Поступила в редакцию 13.03.2013 г."
            ),
            lines=[
                "СВИДЕТЕЛЬСТВА КРАТКИХ ИНТЕНСИВНЫХ ПИКОВ",
                "МАГМАТИЧЕСКОЙ АКТИВНОСТИ НА ЮГЕ СИБИРСКОЙ ПЛАТФОРМЫ",
                "© 2013 г. А. В. Латышев1,2, Р. В. Веселовский1,2, А. В. Иванов3,",
                "А. М. Фетисова1, В. Э. Павлов2",
                "Московский государственный университет имени М.В. Ломоносова, геологический факультет, г. Москва",
                "Поступила в редакцию 13.03.2013 г.",
            ],
        )
    ]

    authors = _extract_authors(
        pages,
        title_match=TitleMatch(
            title="СВИДЕТЕЛЬСТВА КРАТКИХ ИНТЕНСИВНЫХ ПИКОВ МАГМАТИЧЕСКОЙ АКТИВНОСТИ...",
            page_index=0,
            line_index=0,
            score=9,
        ),
        kind="generic_article",
    )

    assert "М.В. Ломоносова" not in authors


def test_falls_back_to_first_page_when_title_zone_has_no_authors():
    pages = [
        PageText(
            number=0,
            text=(
                "The title of the paper\n"
                "Abstract\n"
                "This paper studies the topic.\n"
                "A. B. Ivanov, C. D. Petrov\n"
                "Institute of Earth Sciences"
            ),
            lines=[
                "The title of the paper",
                "Abstract",
                "This paper studies the topic.",
                "A. B. Ivanov, C. D. Petrov",
                "Institute of Earth Sciences",
            ],
        )
    ]

    authors = _extract_authors(
        pages,
        title_match=TitleMatch(
            title="The title of the paper",
            page_index=0,
            line_index=0,
            score=9,
        ),
        kind="generic_article",
    )

    assert authors == ["Ivanov А.В.", "Petrov С.Д."]
