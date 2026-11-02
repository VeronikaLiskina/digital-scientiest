from unittest.mock import patch

import pytest

from app.core.config import settings
from app.schemas.ai_publication_analysis import AIPublicationAnalysisResponse
from app.services import pdf_import as metadata
from app.services.publication_metadata_models import ExtractedPublicationMetadata, PageText, TitleMatch


@pytest.mark.parametrize("text,expected", [
    ("Keywords: Aldan Shield; Siberian Craton; 40Ar/39Ar dating\n1. Introduction", ["aldan shield", "siberian craton", "40ar/39ar dating"]),
    ("Keywords: plume, convection, impact\n669\n*E-mail: test@example.org", ["plume", "convection", "impact"]),
    ("Ключевые слова: U–Pb датирование; Байкальский рифт\nАннотация. Текст.", ["U–Pb датирование", "Байкальский рифт"]),
])
def test_author_keywords_preserve_scientific_terms_and_exclude_page_numbers(text, expected):
    assert metadata._extract_keywords(text) == expected


def test_complete_pdf_title_wins_over_truncated_filename():
    complete = "Evaluation of different models for the origin of the Siberian Traps"
    result = metadata._select_title(
        TitleMatch(complete, 0, 2, 15),
        filename_title="Evaluation of different models for the origin of t", filename_quality=5,
    )
    assert result[0] == complete
    assert result[1] == "pdf"


def test_prominent_title_with_geographical_names_is_not_an_author_list():
    title = "Cenozoic Upper Mantle Plumes in East Siberia and Central Mongolia and Subduction of the Pacific Plate"
    page = PageText(0, title, [title])
    page.layout_title = title
    match = metadata._extract_title([page], kind="generic_article", filename_title=None, allow_filename_fallback=False)
    assert match is not None
    result = metadata._select_title(match, filename_title=None, filename_quality=0)
    assert result[0] == title


def test_ai_title_must_be_present_in_document(monkeypatch):
    original = ExtractedPublicationMetadata(None, 2024, "en", "article", None, [], [], [])
    monkeypatch.setattr(settings, "ai_publication_analysis_mode", "always")
    with patch.object(metadata, "analyze_publication_text", return_value=AIPublicationAnalysisResponse(
        title="Completely Invented Scientific Paper Title",
    )):
        result = metadata._merge_ai_publication_analysis(
            original, full_text="This document contains no title.", filename_title=None,
        )
    assert result.title is None


def test_keyword_suggestions_use_abstract_and_are_marked_separately():
    text = (
        "Geological evolution of the region\nJohn Smith\n2024\nAbstract\n"
        "Mantle plumes cause continental volcanism. Mantle plumes produce basaltic magmas.\n"
        "References\nUnrelated Publisher and Random Author."
    )
    result = metadata._extract_publication_metadata_from_pages([PageText(0, text, text.splitlines())], "scan.pdf")
    assert "mantle plumes" in result.keywords
    assert getattr(result, "keywords_source", None) == "suggested"
    assert not any("publisher" in keyword for keyword in result.keywords)


def test_suggestions_do_not_join_words_across_prepositions():
    title = "Lithospheric Control on Late Cenozoic Magmatism at the Boundary of the Tuva-Mongolian Massif"
    text = title + "\nJohn Smith\n2024"
    result = metadata._extract_publication_metadata_from_pages([PageText(0, text, text.splitlines())], "scan.pdf")
    assert "late cenozoic magmatism" in result.keywords
    assert "control late" not in result.keywords
    assert "control late cenozoic" not in result.keywords


def test_layout_title_preserves_punctuation_between_lines():
    from app.services.pdf_layout_service import LayoutLine, title_from_lines

    lines = [
        LayoutLine("Neogene Basanites in Western Kamchatka: Mineralogy,", .1, .13, .9, .15, .02),
        LayoutLine("Geochemistry, and Geodynamic Setting", .1, .16, .9, .18, .02),
        LayoutLine("Scientific observations and detailed experimental results.", .1, .4, .9, .41, .01),
    ]
    assert title_from_lines(lines) == "Neogene Basanites in Western Kamchatka: Mineralogy, Geochemistry, and Geodynamic Setting"


@pytest.mark.parametrize("filename,title", [
    ("Basanites_of_Mt_Khukhch_First_mineralogical-geoche.pdf", "Basanites of Mt. Khukhch: First Mineralogical-Geochemical Data"),
    ("Evaluation_of_different_models_for_the_origin_of_t (3).pdf", "Evaluation of different models for the origin of the Siberian Traps"),
])
def test_page_layout_selects_title_instead_of_journal_or_filename(monkeypatch, filename, title):
    pymupdf = pytest.importorskip("pymupdf")
    monkeypatch.setattr(settings, "ai_publication_analysis_enabled", False)
    with pymupdf.open() as document:
        page = document.new_page(width=700, height=900)
        page.insert_text((45, 55), "minerals", fontsize=30)
        page.insert_text((45, 92), "DOKLADY EARTH SCIENCES Vol. 409 No. 5", fontsize=10)
        page.insert_textbox((45, 120, 650, 205), title, fontsize=20)
        page.insert_text((45, 235), "John Smith, Jane Brown", fontsize=11)
        page.insert_text((45, 260), "2024", fontsize=10)
        page.insert_text((45, 285), "Abstract", fontsize=10)
        page.insert_textbox((45, 310, 650, 720), "Scientific observations of mantle plumes and basaltic magmatism. " * 30, fontsize=10)
        page.insert_text((45, 850), "DOKLADY EARTH SCIENCES Vol. 409 No. 5", fontsize=12)
        content = document.tobytes()
    result = metadata.extract_publication_metadata_from_bytes(content, original_name=filename)
    assert result.title == title
    assert result.title_source == "pdf"
