from __future__ import annotations

from dataclasses import dataclass
import hashlib
import logging
import os
from pathlib import Path
import re
from threading import BoundedSemaphore
from typing import Any, Literal

from pypdf import PdfReader

from app.core.config import settings
from app.utils.pdf_text import repair_cyrillic_mojibake
from app.utils.text_quality import has_text_corruption, is_readable_text
from app.services.pdf_layout_service import text_from_ocr_data
from app.services.pdf_ocr_cache import get_cached_ocr, store_cached_ocr

try:
    import pymupdf
except ImportError:  # pragma: no cover - depends on the runtime image
    pymupdf = None

try:
    import pytesseract
    from PIL import Image
except ImportError:  # pragma: no cover - depends on the runtime image
    pytesseract = None
    Image = None


MIN_NATIVE_CHARS = 80
OCR_DPI = 300
OCR_LANGUAGES = "rus+eng"
OCR_CONFIG = "--oem 1 --psm 3"
OCR_TIMEOUT_SECONDS = 60
_ocr_slots = BoundedSemaphore(1)
logger = logging.getLogger(__name__)
# Tesseract's OpenMP workers otherwise compete with the search models.
os.environ.setdefault("OMP_THREAD_LIMIT", "2")


PageSource = Literal["native", "ocr", "empty"]
PdfQuality = Literal["text_pdf", "scan_pdf", "mixed_pdf"]


@dataclass(frozen=True, slots=True)
class ExtractedPdfPage:
    """Text selected for one zero-indexed PDF page."""

    index: int
    text: str
    source: PageSource
    layout_title: str | None = None


@dataclass(frozen=True, slots=True)
class PdfTextExtractionResult:
    pages: list[ExtractedPdfPage]
    quality: PdfQuality
    # User-facing page numbers are one-indexed.
    ocr_pages: list[int]
    ocr_errors: list[str]


class OcrUnavailableError(RuntimeError):
    """OCR is unavailable or failed before any text could be recovered."""


def _meaningful_char_count(text: str) -> int:
    return len(re.findall(r"[A-Za-zА-Яа-яЁё0-9]", text))


def _native_text_is_usable(text: str) -> bool:
    meaningful_count = _meaningful_char_count(text)

    if meaningful_count < MIN_NATIVE_CHARS:
        return False

    # A damaged heading can be hidden in an otherwise readable article body.
    heading_lines = [line.strip() for line in text.splitlines() if line.strip()][:8]
    return is_readable_text(text) and not any(
        has_text_corruption(line)
        for line in heading_lines
        if len(line) >= 8
    )


def _ocr_page(document: Any, page_index: int) -> str:
    if pytesseract is None or Image is None:
        raise OcrUnavailableError(
            "Python OCR dependencies are not installed; install PyMuPDF, "
            "pytesseract and Pillow"
        )

    try:
        with _ocr_slots:
            page = document.load_page(page_index)
            pixmap = page.get_pixmap(dpi=OCR_DPI, colorspace=pymupdf.csGRAY, alpha=False)
            with Image.frombytes("L", (pixmap.width, pixmap.height), pixmap.samples) as image:
                data = pytesseract.image_to_data(
                    image,
                    lang=OCR_LANGUAGES,
                    config=OCR_CONFIG,
                    timeout=OCR_TIMEOUT_SECONDS,
                    output_type=pytesseract.Output.DICT,
                )
                text = text_from_ocr_data(data, pixmap.width, pixmap.height)
                latin_count = len(re.findall(r"[A-Za-z]", text))
                cyrillic_count = len(re.findall(r"[А-Яа-яЁё]", text))
                if cyrillic_count and latin_count > max(40, cyrillic_count * 4):
                    # On English scans, the bilingual engine can turn He into
                    # Не and Latin initials into Cyrillic. Reuse the same image.
                    try:
                        english_data = pytesseract.image_to_data(
                            image, lang="eng", config=OCR_CONFIG,
                            timeout=OCR_TIMEOUT_SECONDS,
                            output_type=pytesseract.Output.DICT,
                        )
                        english_text = text_from_ocr_data(english_data, pixmap.width, pixmap.height)
                    except (RuntimeError, OSError, ValueError):
                        logger.warning("English OCR retry failed on page %s", page_index + 1)
                    else:
                        if is_readable_text(english_text):
                            text = english_text
    except pytesseract.TesseractNotFoundError as exc:
        raise OcrUnavailableError(
            "Tesseract OCR is not installed or is unavailable in the container"
        ) from exc
    except (RuntimeError, OSError, ValueError) as exc:
        raise OcrUnavailableError(
            f"OCR failed on page {page_index + 1}: {exc}"
        ) from exc
    return text


def extract_pdf_pages(
    file_path: Path | str,
    *,
    max_pages: int | None = None,
    page_indexes: set[int] | None = None,
    force_ocr: bool = False,
) -> PdfTextExtractionResult:
    """Extract native text and use OCR only for pages with a weak text layer."""

    file_path = Path(file_path)
    ocr_document: Any | None = None
    try:
        reader = PdfReader(str(file_path))
        total_pages = len(reader.pages)
    except Exception:
        # Some fonts/PDF structures fail in pypdf but can still be rendered.
        if pymupdf is None:
            raise
        ocr_document = pymupdf.open(str(file_path))
        reader = None
        total_pages = len(ocr_document)

    if max_pages is not None:
        total_pages = min(total_pages, max(0, max_pages))

    extracted_pages: list[ExtractedPdfPage] = []
    ocr_pages: list[int] = []
    ocr_errors: list[str] = []
    native_pages_count = 0
    ocr_pages_count = 0
    fingerprint: str | None = None
    if settings.pdf_ocr_cache_enabled:
        try:
            with file_path.open("rb") as pdf_file:
                fingerprint = hashlib.file_digest(pdf_file, "sha256").hexdigest()
        except OSError:
            pass  # Extraction can still proceed without caching.

    try:
        for page_index in range(total_pages):
            if page_indexes is not None and page_index not in page_indexes:
                continue
            # An automatic cache entry was created only after the native text
            # failed validation. For identical bytes and settings, reuse it
            # before parsing a potentially huge PDF drawing stream again.
            # Forced recognition has its own key so it cannot override a good
            # native text layer in ordinary extraction.
            cache_key = (
                f"{fingerprint}:{page_index}:{OCR_DPI}:{OCR_LANGUAGES}:{OCR_CONFIG}:forced={force_ocr}"
                if fingerprint else None
            )
            cached_ocr = get_cached_ocr(cache_key) if cache_key else None
            if cached_ocr is not None:
                extracted_pages.append(ExtractedPdfPage(
                    page_index, cached_ocr, "ocr", cached_ocr.layout_title,
                ))
                ocr_pages.append(page_index + 1)
                ocr_pages_count += 1
                continue
            try:
                native_text = (reader.pages[page_index].extract_text() or "").strip() if reader is not None else ""
                native_text = repair_cyrillic_mojibake(native_text)
            except Exception as exc:
                logger.warning("Native PDF extraction failed on page %s: %s", page_index + 1, type(exc).__name__)
                native_text = ""

            native_usable = _native_text_is_usable(native_text)
            if native_usable and not force_ocr:
                extracted_pages.append(
                    ExtractedPdfPage(page_index, native_text, "native")
                )
                native_pages_count += 1
                continue

            try:
                if ocr_document is None:
                    if pymupdf is None:
                        raise OcrUnavailableError(
                            "PyMuPDF is not installed; OCR is unavailable"
                        )

                    try:
                        ocr_document = pymupdf.open(str(file_path))
                    except Exception as exc:
                        raise OcrUnavailableError(
                            f"Could not open PDF for OCR: {exc}"
                        ) from exc

                ocr_text = _ocr_page(ocr_document, page_index)
                if cache_key:
                    store_cached_ocr(cache_key, ocr_text)
            except OcrUnavailableError as exc:
                ocr_errors.append(str(exc))
                ocr_text = ""

            if is_readable_text(ocr_text) and (
                force_ocr or not native_usable
                or _meaningful_char_count(ocr_text) > _meaningful_char_count(native_text)
            ):
                extracted_pages.append(
                    ExtractedPdfPage(page_index, ocr_text, "ocr", getattr(ocr_text, "layout_title", None))
                )
                ocr_pages.append(page_index + 1)
                ocr_pages_count += 1
            elif is_readable_text(native_text, strict=True):
                extracted_pages.append(
                    ExtractedPdfPage(page_index, native_text, "native")
                )
                native_pages_count += 1
            else:
                extracted_pages.append(
                    ExtractedPdfPage(page_index, "", "empty")
                )
    finally:
        if ocr_document is not None:
            ocr_document.close()

    if native_pages_count and ocr_pages_count:
        quality: PdfQuality = "mixed_pdf"
    elif native_pages_count:
        quality = "text_pdf"
    else:

        quality = "scan_pdf"

    if (
        extracted_pages
        and not any(page.text for page in extracted_pages)
        and ocr_errors
    ):
        raise OcrUnavailableError("; ".join(dict.fromkeys(ocr_errors)))

    return PdfTextExtractionResult(
        pages=extracted_pages,
        quality=quality,
        ocr_pages=ocr_pages,
        ocr_errors=ocr_errors,
    )
