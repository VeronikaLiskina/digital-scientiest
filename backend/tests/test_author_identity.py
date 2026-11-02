import pytest

from app.services.author_resolver import _same_author
from app.utils.normalization import format_author_display_name
from app.services.pdf_import import _extract_authors, _extract_authors_from_lines, _find_title_line_index, PageText, TitleMatch


@pytest.mark.parametrize("source,expected", [
    ("A. B. Smith", "Smith A.B."),
    ("John Smith", "John Smith"),
    ("Huaiyu He", "Huaiyu He"),
    ("M. Yu. Puzankov", "Пузанков М.Ю."),
    ("A. Boven", "Boven A."),
])
def test_preserves_valid_english_authors_outside_known_surname_list(source, expected):
    assert format_author_display_name(source) == expected


@pytest.mark.parametrize("russian,english", [
    ("Веселовский Р.В.", "R. V. Veselovsky"),
    ("Николаева И.В.", "Irina V. Nikolaeva"),
    ("Пузанков М.Ю.", "M. Yu. Puzankov"),
    ("Иванов Алексей Викторович", "Alexei Ivanov"),
])
def test_matches_transliterated_names_with_compatible_initials(russian, english):
    assert _same_author(russian, english)


@pytest.mark.parametrize("left,right", [
    ("Иванов А.В.", "A. B. Ivanov"),
    ("Иванов А.В.", "A. V. Ivanova"),
    ("Иванов А.В.", "P. V. Ivanov"),
])
def test_does_not_merge_different_people(left, right):
    assert not _same_author(left, right)


def test_affiliation_letters_do_not_become_part_of_surname():
    authors = _extract_authors_from_lines([
        "Alexei V. Ivanov a,*, Irina V. Nikolaeva c, John Smith b",
    ])
    assert "Иванов А.В." in authors
    assert all("Ivanova" not in name and "Nikolaevac" not in name for name in authors)
    assert "John Smith" in authors


def test_camelcase_surnames_are_not_split_into_another_author():
    authors = _extract_authors_from_lines(["S. A. DuFrane, J. A. McDonald"])
    assert authors == ["Дюфрейн С.А.", "McDonald J.A."]


def test_long_multiline_title_does_not_truncate_eight_author_byline():
    lines = [
        "Neogene Basanites in Western Kamchatka: Mineralogy,",
        "Geochemistry, and Geodynamic Setting",
        "A. B. Perepelov", "M. Yu. Puzankov", "A. V. Ivanov",
        "T. M. Filosofova", "E. I. Demonterova", "E. V. Smirnova",
        "L. A. Chuvashova", "and T. A. Yasnygina",
        "Vinogradov Institute of Geochemistry", "Abstract", "Scientific text.",
    ]
    authors = _extract_authors(
        [PageText(0, "\n".join(lines), lines)],
        title_match=TitleMatch(" ".join(lines[:2]), 0, 0, 15, from_layout=True),
        kind="generic_article",
    )
    assert authors == ["Перепелов А.Б.", "Пузанков М.Ю.", "Иванов А.В.",
                       "Философова Т.М.", "Демонтерова Е.И.", "Смирнова Е.В.",
                       "Чувашова Л.А.", "Ясныгина Т.А."]


def test_layout_title_starts_at_heading_instead_of_journal_homepage():
    title = "Volcanism in the Baikal rift: 40 years of active-versus-passive model discussion"
    lines = ["Earth-Science Reviews", "Contents lists available at ScienceDirect",
             "Earth-Science Reviews", "journal homepage: www.elsevier.com",
             "Volcanism in the Baikal rift: 40 years of active-versus-passive",
             "model discussion", "Alexei V. Ivanov a, Elena I. Demonterova b, Huaiyu He c",
             "Institute of the Earth's Crust", "Abstract", "Scientific body."]
    page = PageText(0, "\n".join(lines), lines, layout_title=title)
    index = _find_title_line_index(page, title)
    assert index == 4
    authors = _extract_authors([page], title_match=TitleMatch(title, 0, index, 15, from_layout=True), kind="generic_article")
    assert authors == ["Иванов А.В.", "Демонтерова Е.И.", "Huaiyu He"]


def test_title_geometry_does_not_join_english_byline_to_heading():
    from app.services.pdf_layout_service import LayoutLine, title_from_lines
    lines = [
        LayoutLine("Dating of intrusive magmatism in Siberia", .1, .15, .9, .17, .02),
        LayoutLine("Alexei V. Ivanov a, Huaiyu He b, Liekun Yang b", .1, .18, .9, .20, .02),
        LayoutLine("A long readable scientific body with several words.", .1, .5, .9, .51, .01),
    ]
    assert title_from_lines(lines) == "Dating of intrusive magmatism in Siberia"


def test_ocr_on_third_metadata_page_is_not_treated_as_native_author_evidence():
    from app.services.pdf_import import _extract_publication_metadata_from_pages
    title = "Geological evolution of eastern Siberia"
    first = [title, "Abstract", "The scientific study describes regional geological evolution.", "2024"]
    pages = [PageText(0, "\n".join(first), first, layout_title=title),
             PageText(1, "A readable body of the scientific publication.", ["A readable body of the scientific publication."]),
             PageText(2, "© 2024 Иванов А.В., Петров П.П.", ["© 2024 Иванов А.В., Петров П.П."], source="ocr")]
    metadata = _extract_publication_metadata_from_pages(pages, "paper.pdf")
    assert metadata.authors_source == "ocr"


def test_contents_page_does_not_supply_neighbor_article_authors():
    lines = ["Journal of Earth System Science", "CONTENTS",
             "Occurrence of volcanic ash in India", "Rachna Raj",
             "Groundwater chemistry from Tamil Nadu", "M. V. Prasanna, John Peter"]
    page = PageText(0, "\n".join(lines), lines)
    authors = _extract_authors([page], title_match=TitleMatch(lines[2], 0, 2, 15), kind="generic_article")
    assert authors == []


def test_superscript_affiliation_is_removed_without_changing_female_surname():
    from app.services.pdf_layout_service import clean_author_spans
    spans = [{"text": "A. V. Ivanov", "size": 12, "flags": 0},
             {"text": "a", "size": 7, "flags": 1},
             {"text": ", A. V. Ivanova", "size": 12, "flags": 0},
             {"text": "b", "size": 7, "flags": 1}]
    assert clean_author_spans(spans) == "A. V. Ivanov, A. V. Ivanova"


def test_space_after_superscript_keeps_and_separate_from_surname():
    from app.services.pdf_layout_service import clean_author_spans
    spans = [{"text": "Viktor A. Gorovoy", "size": 10, "flags": 20},
             {"text": "1", "size": 7, "flags": 21},
             {"text": " ", "size": 10, "flags": 21},
             {"text": "and Nikolay V. Vladykin", "size": 10, "flags": 20}]
    assert clean_author_spans(spans) == "Viktor A. Gorovoy and Nikolay V. Vladykin"


def test_hyphenated_asian_initials_are_not_truncated():
    assert _extract_authors_from_lines(["C.-H. Hung, S.-L. Chung, K.-L. Wang"]) == ["Hung C.H.", "Chung S.L.", "Wang K.L."]


def test_academician_presenting_paper_is_not_an_author():
    lines = ["Formation History of the Tuva Mongolian Massif",
             "E. I. Demonterova, A. V. Ivanov",
             "Presented by Academician M.I. Kuzmin May 4, 2011", "Received June 7, 2011"]
    assert _extract_authors([PageText(0, "\n".join(lines), lines)],
        title_match=TitleMatch(lines[0], 0, 0, 15), kind="generic_article") == ["Демонтерова Е.И.", "Иванов А.В."]


def test_single_transliterated_initial_is_preserved():
    assert _extract_authors_from_lines(["Yo. Iizuka"]) == ["Iizuka Yo."]
