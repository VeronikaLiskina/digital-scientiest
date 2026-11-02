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


@pytest.mark.parametrize("broken_heading", [
    "(cid:51)(cid:52)(cid:53)(cid:54)",
    "\ue010\ue011\ue012\ue013" * 10,
    "Мaгнитныe cвoйcтва гopных пopoд",
    "РњР°РіРЅРёС‚РЅС‹Рµ СЃРІРѕР№СЃС‚РІР°",
    "M A G N E T I C P R O P E R T I E S",
    "Ïàëåîçîéñêàÿ ýâîëþöèÿ ðåãèîíà",
])
def test_recovers_broken_heading_even_with_long_readable_body(monkeypatch, tmp_path, broken_heading):
    native = broken_heading + "\n" + "A readable scientific body with many words. " * 40
    configure_pdf(monkeypatch, [native])
    recognized = "Magnetic properties of Siberian rocks\nIvan Ivanov, Petr Petrov\n2024"
    monkeypatch.setattr(pdf_text_extraction, "_ocr_page", lambda *_: recognized)

    result = pdf_text_extraction.extract_pdf_pages(tmp_path / "broken.pdf")

    assert result.pages[0].source == "ocr"
    assert result.pages[0].text == recognized  # Quality wins over character count.


def test_does_not_replace_readable_native_text_with_ocr_garbage(monkeypatch, tmp_path):
    configure_pdf(monkeypatch, ["Magnetic properties of Siberian rocks"])
    monkeypatch.setattr(pdf_text_extraction, "_ocr_page", lambda *_: "(cid:123)" * 100)

    result = pdf_text_extraction.extract_pdf_pages(tmp_path / "bad-ocr.pdf")

    assert result.pages[0].source == "native"
    assert result.pages[0].text == "Magnetic properties of Siberian rocks"


def test_does_not_return_garbage_when_both_extractions_are_broken(monkeypatch, tmp_path):
    configure_pdf(monkeypatch, ["(cid:123)" * 100])
    monkeypatch.setattr(pdf_text_extraction, "_ocr_page", lambda *_: "\ue000" * 100)

    result = pdf_text_extraction.extract_pdf_pages(tmp_path / "unreadable.pdf")

    assert result.pages[0].text == ""
    assert result.pages[0].source == "empty"


def test_forced_ocr_reads_only_selected_pages_and_closes_document(monkeypatch, tmp_path):
    document = configure_pdf(monkeypatch, ["Native publication text " * 10] * 5)
    seen = []

    def recognize(_document, page_index):
        seen.append(page_index)
        return "Magnetic properties of Siberian rocks"

    monkeypatch.setattr(pdf_text_extraction, "_ocr_page", recognize)
    result = pdf_text_extraction.extract_pdf_pages(
        tmp_path / "selected.pdf", page_indexes={1}, force_ocr=True,
    )

    assert seen == [1]
    assert result.ocr_pages == [2]
    assert [page.index for page in result.pages] == [1]
    assert document.closed


def test_recovers_when_native_page_extraction_raises(monkeypatch, tmp_path):
    configure_pdf(monkeypatch, [""])

    def broken_text(_page):
        raise ValueError("Unsupported font mapping")

    monkeypatch.setattr(FakePage, "extract_text", broken_text)
    monkeypatch.setattr(pdf_text_extraction, "_ocr_page", lambda *_: "Magnetic properties of Siberian rocks")

    result = pdf_text_extraction.extract_pdf_pages(tmp_path / "bad-font.pdf")

    assert result.pages[0].source == "ocr"


def test_english_ocr_retries_without_russian_glyph_substitutions(monkeypatch):
    calls = []

    def recognize(_image, *, lang, **_kwargs):
        calls.append(lang)
        if lang == "rus+eng":
            text = "Volcanism in the Baikal rift and magnetic properties Alexei V. Ivanov, Huaiyu Не"
        else:
            text = "Volcanism in the Baikal rift and magnetic properties Alexei V. Ivanov, Huaiyu He"
        words = text.split()
        return {"text": words, "conf": [95] * len(words),
                "block_num": [1] * len(words), "par_num": [1] * len(words),
                "line_num": [1] * len(words), "left": list(range(len(words))),
                "top": [1] * len(words), "width": [1] * len(words), "height": [1] * len(words)}

    image = SimpleNamespace(__enter__=lambda self: self, __exit__=lambda *args: None)

    class FakeImage:
        def __enter__(self):
            return image

        def __exit__(self, *_args):
            pass

    monkeypatch.setattr(pdf_text_extraction, "pymupdf", SimpleNamespace(csGRAY=0))
    monkeypatch.setattr(pdf_text_extraction, "Image", SimpleNamespace(frombytes=lambda *_: FakeImage()))
    monkeypatch.setattr(pdf_text_extraction, "pytesseract", SimpleNamespace(
        image_to_data=recognize, Output=SimpleNamespace(DICT="dict"),
    ))
    pixmap = SimpleNamespace(width=10, height=10, samples=b"pixels")
    document = SimpleNamespace(load_page=lambda _: SimpleNamespace(get_pixmap=lambda **_: pixmap))

    text = pdf_text_extraction._ocr_page(document, 0)

    assert calls == ["rus+eng", "eng"]
    assert "Huaiyu He" in text


def test_reuses_ocr_when_preview_and_saved_pdf_have_identical_content(monkeypatch, tmp_path, ocr_cache):
    configure_pdf(monkeypatch, [""])
    preview_path = tmp_path / "preview.pdf"
    saved_path = tmp_path / "saved.pdf"
    preview_path.write_bytes(b"pdf content shared by preview and upload")
    saved_path.write_bytes(preview_path.read_bytes())
    calls = []

    def recognize(_document, page_index):
        calls.append(page_index)
        return "Volcanism in the Baikal rift and mantle processes"

    monkeypatch.setattr(pdf_text_extraction, "_ocr_page", recognize)
    preview = pdf_text_extraction.extract_pdf_pages(preview_path)
    monkeypatch.setattr(FakePage, "extract_text", lambda _: pytest.fail(
        "A previously recognized page should bypass slow native text parsing",
    ))
    saved = pdf_text_extraction.extract_pdf_pages(saved_path)

    assert saved == preview
    assert calls == [0]
