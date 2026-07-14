from types import SimpleNamespace

import pytest

from app.services import pdf_text_extraction
from app.services.pdf_text_extraction import OcrUnavailableError


class FakePage:
    def __init__(self, text: str) -> None:
        self.text = text

    def extract_text(self) -> str:
        return self.text


class FakeReader:
    def __init__(self, texts: list[str]) -> None:
        self.pages = [FakePage(text) for text in texts]


class FakeOcrDocument:
    def __init__(self) -> None:
        self.closed = False

    def close(self) -> None:
        self.closed = True


def configure_pdf(monkeypatch, native_texts: list[str]) -> FakeOcrDocument:
    document = FakeOcrDocument()
    monkeypatch.setattr(
        pdf_text_extraction,
        "PdfReader",
        lambda _path: FakeReader(native_texts),
    )
    monkeypatch.setattr(
        pdf_text_extraction,
        "pymupdf",
        SimpleNamespace(open=lambda _path: document),
    )
    return document


def test_uses_native_text_without_opening_ocr(monkeypatch, tmp_path):
    configure_pdf(monkeypatch, ["Native publication text " * 10])
    monkeypatch.setattr(
        pdf_text_extraction.pymupdf,
        "open",
        lambda _path: pytest.fail("OCR must not be opened for a good text layer"),
    )

    result = pdf_text_extraction.extract_pdf_pages(tmp_path / "text.pdf")

    assert result.quality == "text_pdf"
    assert result.pages[0].source == "native"
    assert result.ocr_pages == []


def test_uses_ocr_only_for_weak_page(monkeypatch, tmp_path):
    document = configure_pdf(
        monkeypatch,
        ["Native publication text " * 10, "short"],
    )
    monkeypatch.setattr(
        pdf_text_extraction,
        "_ocr_page",
        lambda _document, page_index: "Распознанный текст страницы" * (page_index + 1),
    )

    result = pdf_text_extraction.extract_pdf_pages(tmp_path / "mixed.pdf")

    assert result.quality == "mixed_pdf"
    assert [page.source for page in result.pages] == ["native", "ocr"]
    assert result.ocr_pages == [2]
    assert document.closed is True


def test_keeps_short_native_text_when_ocr_page_fails(monkeypatch, tmp_path):
    configure_pdf(monkeypatch, ["short native text"])

    def fail_ocr(_document, _page_index):
        raise OcrUnavailableError("OCR unavailable")

    monkeypatch.setattr(pdf_text_extraction, "_ocr_page", fail_ocr)

    result = pdf_text_extraction.extract_pdf_pages(tmp_path / "fallback.pdf")

    assert result.quality == "text_pdf"
    assert result.pages[0].source == "native"
    assert result.pages[0].text == "short native text"
    assert result.ocr_errors == ["OCR unavailable"]


def test_raises_when_scan_is_empty_and_ocr_is_unavailable(monkeypatch, tmp_path):
    configure_pdf(monkeypatch, [""])

    def fail_ocr(_document, _page_index):
        raise OcrUnavailableError("OCR unavailable")

    monkeypatch.setattr(pdf_text_extraction, "_ocr_page", fail_ocr)

    with pytest.raises(OcrUnavailableError, match="OCR unavailable"):
        pdf_text_extraction.extract_pdf_pages(tmp_path / "scan.pdf")


def test_empty_pdf_is_not_classified_as_text_pdf(monkeypatch, tmp_path):
    configure_pdf(monkeypatch, [""])
    monkeypatch.setattr(
        pdf_text_extraction,
        "_ocr_page",
        lambda _document, _page_index: "",
    )

    result = pdf_text_extraction.extract_pdf_pages(tmp_path / "empty.pdf")

    assert result.quality == "scan_pdf"
    assert result.pages[0].source == "empty"
