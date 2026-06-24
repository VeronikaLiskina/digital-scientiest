from app.services.pdf_import import PageText
from app.services.pdf_import import _extract_title
from app.services.pdf_import import _filename_title
from app.services.pdf_import import _filename_title_candidate
from app.services.pdf_import import _filename_title_quality
from app.services.pdf_import import _pdf_title_quality
from app.services.pdf_import import _select_title
from app.services.pdf_import import _should_prefer_filename_title


def test_filename_title_rejects_technical_pdf_names():
    assert _filename_title("550e8400-e29b-41d4-a716-446655440000.pdf") is None
    assert _filename_title("10.1016_j.tecto.2024.230123.pdf") is None
    assert _filename_title("download.pdf") is None
    assert _filename_title("fulltext_2.pdf") is None
    assert _filename_title("027_rannekembriyskiy_vysokokalievyy_magmatizm_na_severo_vostoke_sibirskogo_kratona_chekuro") is None
    assert _filename_title("021_ispolzovanie_sostava_doleritov_dlya_rekonstruktsii.pdf") is None
    assert _filename_title("027_rannekembriyskiy_vysokokalievy_m.pdf") is None
    assert _filename_title("article_001.pdf") is None
    assert _filename_title("2024_05_17_ab12.pdf") is None


def test_filename_title_accepts_human_article_name():
    assert (
        _filename_title("Paleozoic evolution of the Siberian craton.pdf")
        == "Paleozoic evolution of the Siberian craton"
    )


def test_article_title_from_page_is_preferred_over_filename():
    pages = [
        PageText(
            number=0,
            text=(
                "Real Article Title About Magmatic Evolution\n"
                "A. Smith, B. Jones\n"
                "Abstract\n"
                "The article body starts here."
            ),
            lines=[
                "Real Article Title About Magmatic Evolution",
                "A. Smith, B. Jones",
                "Abstract",
                "The article body starts here.",
            ],
        )
    ]

    match = _extract_title(
        pages,
        kind="generic_article",
        filename_title="Completely Different Human Filename Title",
    )

    assert match is not None
    assert match.title == "Real Article Title About Magmatic Evolution"


def test_numbered_translit_filename_does_not_replace_pdf_title():
    pages = [
        PageText(
            number=0,
            text=(
                "Результаты LA-ICP-MS датирования цирконов\n"
                "Иванов И.И.\n"
                "Аннотация\n"
                "Текст статьи."
            ),
            lines=[
                "Результаты LA-ICP-MS датирования цирконов",
                "Иванов И.И.",
                "Аннотация",
                "Текст статьи.",
            ],
        )
    ]

    match = _extract_title(
        pages,
        kind="generic_article",
        filename_title=_filename_title("020_rezultaty_la_icp_ms_datirovaniya_tsirkonov.pdf"),
    )

    assert match is not None
    assert match.title == "Результаты LA-ICP-MS датирования цирконов"


def test_title_stops_before_latin_author_lines():
    pages = [
        PageText(
            number=0,
            text=(
                "Matters arising https://doi.org/10.1038/s41467-023-36570-5\n"
                "Reply to: Increase of P-wave velocity due to\n"
                "melt in the mantle at the Gakkel Ridge\n"
                "Ivan Koulakov 1,2 ,V e r aS c h l i n d w e i n3,4, Mingqi Liu 5, Taras Gerya 5\n"
                "Andrey Jakovlev 1 & Aleksey Ivanov 2\n"
                "REPLYING TO Z. Yu & S. C. Singh Nature Communications"
            ),
            lines=[
                "Matters arising https://doi.org/10.1038/s41467-023-36570-5",
                "Reply to: Increase of P-wave velocity due to",
                "melt in the mantle at the Gakkel Ridge",
                "Ivan Koulakov 1,2 ,V e r aS c h l i n d w e i n3,4, Mingqi Liu 5, Taras Gerya 5",
                "Andrey Jakovlev 1 & Aleksey Ivanov 2",
                "REPLYING TO Z. Yu & S. C. Singh Nature Communications",
            ],
        )
    ]

    match = _extract_title(
        pages,
        kind="generic_article",
        filename_title=None,
    )

    assert match is not None
    assert match.title == (
        "Reply to: Increase of P-wave velocity due to "
        "melt in the mantle at the Gakkel Ridge"
    )


def test_select_title_prefers_pdf_over_technical_filename():
    filename_title = _filename_title_candidate("027_rannekembriyskiy_vysokokalievy_m.pdf")
    filename_quality = _filename_title_quality(
        filename_title,
        raw_title="027_rannekembriyskiy_vysokokalievy_m",
    )
    pages = [
        PageText(
            number=0,
            text=(
                "Раннекембрийский высококалиевый магматизм\n"
                "на северо-востоке Сибирского кратона\n"
                "Иванов И.И.\n"
                "Аннотация"
            ),
            lines=[
                "Раннекембрийский высококалиевый магматизм",
                "на северо-востоке Сибирского кратона",
                "Иванов И.И.",
                "Аннотация",
            ],
        )
    ]

    match = _extract_title(
        pages,
        kind="generic_article",
        filename_title=None,
        allow_filename_fallback=False,
    )

    assert match is not None
    assert _pdf_title_quality(match) > filename_quality

    title, source, confidence, warning = _select_title(
        match,
        filename_title=filename_title,
        filename_quality=filename_quality,
    )

    assert title == "Раннекембрийский высококалиевый магматизм на северо-востоке Сибирского кратона"
    assert source == "pdf"
    assert confidence == "high"
    assert warning is None


def test_select_title_uses_human_filename_only_as_fallback():
    filename_title = _filename_title_candidate("Paleozoic evolution of the Siberian craton.pdf")
    filename_quality = _filename_title_quality(
        filename_title,
        raw_title="Paleozoic evolution of the Siberian craton",
    )

    title, source, confidence, warning = _select_title(
        None,
        filename_title=filename_title,
        filename_quality=filename_quality,
    )

    assert title == "Paleozoic evolution of the Siberian craton"
    assert source == "filename"
    assert confidence in {"medium", "high"}
    assert warning == "Название взято из имени файла, проверьте корректность."


def test_filename_is_only_fallback_for_missing_or_bad_extracted_title():
    filename_title = "Paleozoic evolution of the Siberian craton"

    assert _should_prefer_filename_title(None, filename_title) is True
    assert (
        _should_prefer_filename_title(
            "Real Article Title About Magmatic Evolution",
            filename_title,
        )
        is False
    )
    assert (
        _should_prefer_filename_title(
            None,
            "550e8400-e29b-41d4-a716-446655440000",
        )
        is False
    )
