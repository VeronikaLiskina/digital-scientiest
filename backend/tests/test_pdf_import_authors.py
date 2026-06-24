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
