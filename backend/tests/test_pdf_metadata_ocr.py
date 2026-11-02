from io import BytesIO
from types import SimpleNamespace

import pytest
from pypdf import PdfWriter

from app.core.config import settings
from app.services import pdf_import, pdf_text_extraction
from app.services.publication_metadata_models import PageText


TITLE = "Магнитные свойства базальтов Восточной Сибири"
RECOGNIZED = (
    TITLE + "\nИванов И.И., Петров П.П.\n"
    "Аннотация\nИзучены магнитные свойства базальтов региона.\n"
    "Ключевые слова: магнетизм; базальты; Восточная Сибирь\n"
    "2024\nDOI: 10.1234/magnetism.2024\n"
)


def scan_pdf() -> bytes:
    writer = PdfWriter()
    writer.add_blank_page(width=595, height=842)
    stream = BytesIO()
    writer.write(stream)
    return stream.getvalue()


@pytest.mark.parametrize("route", ["preview", "stored", "batch"])
async def test_upload_flows_extract_metadata_from_ocr(client, monkeypatch, tmp_path, route):
    monkeypatch.setattr(settings, "upload_dir", str(tmp_path))
    monkeypatch.setattr(settings, "ai_publication_analysis_enabled", False)
    monkeypatch.setattr(pdf_text_extraction, "_ocr_page", lambda *_: RECOGNIZED)
    monkeypatch.setattr(pdf_text_extraction, "pymupdf", SimpleNamespace(
        open=lambda _path: SimpleNamespace(close=lambda: None),
    ))
    files = {"file": ("scan.pdf", scan_pdf(), "application/pdf")}

    if route == "preview":
        response = await client.post("/api/source-files/extract-metadata", files=files)
        data = response.json()["extracted"]
        assert (await client.get("/api/source-files")).json() == []
    elif route == "stored":
        uploaded = await client.post("/api/source-files/upload", files=files)
        assert uploaded.status_code == 201
        response = await client.post(f'/api/source-files/{uploaded.json()["id"]}/extract-metadata')
        data = response.json()["extracted"]
    else:
        response = await client.post("/api/publication-imports", files={"files": files["file"]})
        assert response.status_code == 201
        item = response.json()["items"][0]
        assert item["status"] == "needs_review", item
        data = item["extracted_metadata"]

    assert response.status_code in {200, 201}
    assert data["title"] == TITLE
    assert data["title_source"] == "ocr"
    assert data["title_confidence"] == "medium"
    assert data["title_warning"]
    assert data["authors"] == ["Иванов И.И.", "Петров П.П."]
    assert data["year"] == 2024
    assert data["doi"] == "10.1234/magnetism.2024"
    assert "Магнетизм" in data["keywords"]
    assert (await client.get("/api/publications")).json() == []


def test_metadata_retries_first_native_pages_before_calling_api(monkeypatch, tmp_path):
    native = PageText(0, "Native body without a heading", ["Native body without a heading"])
    recovered = PageText(0, RECOGNIZED, RECOGNIZED.splitlines(), source="ocr")
    calls = []

    def extract_pages(_path, **kwargs):
        calls.append(kwargs)
        return [recovered] if kwargs.get("force_ocr") else [native]

    monkeypatch.setattr(pdf_import, "_extract_pages", extract_pages)
    monkeypatch.setattr(settings, "ai_publication_analysis_enabled", False)
    result = pdf_import.extract_publication_metadata_from_pdf(tmp_path / "scan.pdf")

    assert result.title == TITLE
    assert result.authors == ["Иванов И.И.", "Петров П.П."]
    assert calls == [{}, {"page_indexes": {0}, "force_ocr": True}]


def test_complete_native_metadata_does_not_trigger_extra_ocr(monkeypatch, tmp_path):
    calls = []

    def extract_pages(_path, **kwargs):
        calls.append(kwargs)
        return [PageText(0, RECOGNIZED, RECOGNIZED.splitlines())]

    monkeypatch.setattr(pdf_import, "_extract_pages", extract_pages)
    monkeypatch.setattr(settings, "ai_publication_analysis_enabled", False)
    result = pdf_import.extract_publication_metadata_from_pdf(tmp_path / "article.pdf")

    assert result.title == TITLE
    assert calls == [{}]


@pytest.mark.parametrize("broken", ["(cid:123)" * 5, "Мaгнитныe cвoйcтва пopoд", "\ue010" * 15])
def test_garbled_titles_are_not_taken_from_pdf_or_filename(broken):
    assert pdf_import._filename_title_quality(broken, raw_title=broken) == 0
    assert pdf_import._is_bad_extracted_title(broken)


def test_ocr_title_ignores_journal_checkmark_and_preserves_last_author_initial():
    text = (
        "Earth-Science Reviews 148 (2015) 18-43\n"
        "Contents lists available at ScienceDirect\n"
        "Earth-Science Reviews\n"
        "journal homepage: www.elsevier.com/locate/earscirev\n"
        "Volcanism in the Baikal rift: 40 years of active-versus-passive @ coven\n"
        "model discussion\n"
        "Alexei V. Ivanov, Elena I. Demonterova\n"
        "Abstract\nIn this review we focus on the volcanism."
    )
    page = PageText(0, text, pdf_import._extract_metadata_lines(text), source="ocr")
    result = pdf_import._extract_publication_metadata_from_pages([page], "article_001.pdf")

    assert result.title == "Volcanism in the Baikal rift: 40 years of active-versus-passive model discussion"
    assert result.authors == ["Иванов А.В.", "Демонтерова Е.И."]
