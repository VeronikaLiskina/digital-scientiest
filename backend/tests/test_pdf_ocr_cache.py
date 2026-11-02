from types import SimpleNamespace

import pytest
from redis.exceptions import ConnectionError

from app.services import pdf_text_extraction
from app.services.pdf_layout_service import OCRText
from app.services.pdf_text_extraction import OcrUnavailableError
from app.core.config import settings


TEXT = "Volcanism in the Baikal rift and mantle processes"


def test_cache_outage_does_not_add_a_timeout_for_every_pdf_page(monkeypatch):
    from app.services import pdf_ocr_cache

    calls = []

    def offline():
        calls.append(1)
        raise ConnectionError("Redis offline")

    monkeypatch.setattr(settings, "pdf_ocr_cache_enabled", True)
    monkeypatch.setattr(pdf_ocr_cache, "_unavailable_until", 0, raising=False)
    monkeypatch.setattr(pdf_ocr_cache, "_client", offline)
    for page in range(20):
        assert pdf_ocr_cache.get_cached_ocr(str(page)) is None
        pdf_ocr_cache.store_cached_ocr(str(page), TEXT)
    assert calls == [1]


def configure_scan(monkeypatch, tmp_path):
    path = tmp_path / "scan.pdf"
    path.write_bytes(b"first scanned PDF")
    monkeypatch.setattr(pdf_text_extraction, "PdfReader", lambda _: SimpleNamespace(
        pages=[SimpleNamespace(extract_text=lambda: "")],
    ))
    monkeypatch.setattr(pdf_text_extraction, "pymupdf", SimpleNamespace(
        open=lambda _: SimpleNamespace(close=lambda: None),
    ))
    return path


def test_cache_keeps_layout_title_and_bounds_redis_storage(ocr_cache, monkeypatch):
    monkeypatch.setattr(ocr_cache, "MAX_ENTRIES", 2)
    ocr_cache.store_cached_ocr("old", TEXT)
    ocr_cache.store_cached_ocr("second", TEXT)
    ocr_cache.store_cached_ocr("new", OCRText(TEXT, "Volcanism in the Baikal rift"))

    assert ocr_cache.get_cached_ocr("old") is None
    assert ocr_cache.get_cached_ocr("second") == TEXT
    restored = ocr_cache.get_cached_ocr("new")
    assert restored == TEXT
    assert restored.layout_title == "Volcanism in the Baikal rift"
    assert ocr_cache._client().hlen(ocr_cache.CACHE_KEY) == 2
    assert 0 < ocr_cache._client().ttl(ocr_cache.CACHE_KEY) <= ocr_cache.TTL_SECONDS


def test_cache_does_not_store_empty_corrupt_or_oversized_text(ocr_cache):
    for key, text in [("empty", ""), ("corrupt", "(cid:123)" * 100),
                      ("huge", TEXT * ocr_cache.MAX_ENTRY_BYTES)]:
        ocr_cache.store_cached_ocr(key, text)
        assert ocr_cache.get_cached_ocr(key) is None


def test_corrupt_cached_json_is_treated_as_a_miss(ocr_cache):
    ocr_cache._client().hset(ocr_cache.CACHE_KEY, "broken", "not json")
    assert ocr_cache.get_cached_ocr("broken") is None


def test_changed_file_and_recognition_settings_invalidate_ocr(ocr_cache, monkeypatch, tmp_path):
    path = configure_scan(monkeypatch, tmp_path)
    calls = []

    def recognize(*_args):
        calls.append(1)
        return OCRText(TEXT, "Volcanism in the Baikal rift")

    monkeypatch.setattr(pdf_text_extraction, "_ocr_page", recognize)
    first = pdf_text_extraction.extract_pdf_pages(path)
    assert pdf_text_extraction.extract_pdf_pages(path) == first
    path.write_bytes(b"a changed scanned PDF at the same path")
    assert pdf_text_extraction.extract_pdf_pages(path) == first
    monkeypatch.setattr(pdf_text_extraction, "OCR_DPI", 301)
    assert pdf_text_extraction.extract_pdf_pages(path) == first
    assert len(calls) == 3


def test_ocr_errors_are_not_cached(ocr_cache, monkeypatch, tmp_path):
    path = configure_scan(monkeypatch, tmp_path)

    def unavailable(*_args):
        raise OcrUnavailableError("temporary OCR failure")

    monkeypatch.setattr(pdf_text_extraction, "_ocr_page", unavailable)
    with pytest.raises(OcrUnavailableError, match="temporary OCR failure"):
        pdf_text_extraction.extract_pdf_pages(path)
    monkeypatch.setattr(pdf_text_extraction, "_ocr_page", lambda *_: TEXT)
    assert pdf_text_extraction.extract_pdf_pages(path).pages[0].text == TEXT


def test_cache_outage_does_not_break_pdf_extraction(ocr_cache, monkeypatch, tmp_path):
    path = configure_scan(monkeypatch, tmp_path)

    def offline():
        raise ConnectionError("Redis offline")

    monkeypatch.setattr(ocr_cache, "_client", offline)
    monkeypatch.setattr(pdf_text_extraction, "_ocr_page", lambda *_: TEXT)
    assert pdf_text_extraction.extract_pdf_pages(path).pages[0].text == TEXT


def test_forced_ocr_cache_does_not_replace_good_native_text(ocr_cache, monkeypatch, tmp_path):
    path = configure_scan(monkeypatch, tmp_path)
    native = "Readable native scientific text about rock properties. " * 10
    monkeypatch.setattr(pdf_text_extraction, "PdfReader", lambda _: SimpleNamespace(
        pages=[SimpleNamespace(extract_text=lambda: native)],
    ))
    monkeypatch.setattr(pdf_text_extraction, "_ocr_page", lambda *_: TEXT)

    forced = pdf_text_extraction.extract_pdf_pages(path, force_ocr=True)
    normal = pdf_text_extraction.extract_pdf_pages(path)
    assert forced.pages[0].source == "ocr"
    assert normal.pages[0].source == "native"
    assert normal.pages[0].text == native.strip()
