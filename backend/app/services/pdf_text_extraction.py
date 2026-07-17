from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
from typing import Any, Literal

from pypdf import PdfReader

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


PageSource = Literal["native", "ocr", "empty"]
PdfQuality = Literal["text_pdf", "scan_pdf", "mixed_pdf"]


@dataclass(frozen=True, slots=True)
class ExtractedPdfPage:
    """Text selected for one zero-indexed PDF page."""

    index: int
    text: str
    source: PageSource


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

    non_space_count = len(re.sub(r"\s", "", text))

    if non_space_count == 0:
        return False

    # A broken text layer often consists mostly of replacement/control symbols.
    replacement_count = text.count("\ufffd") + len(
        re.findall(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", text)
    )

    return (
        meaningful_count / non_space_count >= 0.45
        and replacement_count <= max(2, meaningful_count // 30)
    )


def _ocr_page(document: Any, page_index: int) -> str:
    if pytesseract is None or Image is None:
        raise OcrUnavailableError(
            "Python OCR dependencies are not installed; install PyMuPDF, "
            "pytesseract and Pillow"
        )

    page = document.load_page(page_index)
    pixmap = page.get_pixmap(
        dpi=OCR_DPI,
        colorspace=pymupdf.csRGB,
        alpha=False,
    )
    image = Image.frombytes(
        "RGB",
        (pixmap.width, pixmap.height),
        pixmap.samples,
    )

    try:
        text = pytesseract.image_to_string(
            image,
            lang=OCR_LANGUAGES,
            config=OCR_CONFIG,
            timeout=OCR_TIMEOUT_SECONDS,
        )
    except pytesseract.TesseractNotFoundError as exc:
        raise OcrUnavailableError(
            "Tesseract OCR is not installed or is unavailable in the container"
        ) from exc
    except RuntimeError as exc:
        raise OcrUnavailableError(
            f"OCR failed on page {page_index + 1}: {exc}"
        ) from exc
    finally:
        image.close()

    return text.strip()


def extract_pdf_pages(
    file_path: Path | str,
    *,
    max_pages: int | None = None,
) -> PdfTextExtractionResult:
    """Extract native text and use OCR only for pages with a weak text layer."""

    file_path = Path(file_path)
    reader = PdfReader(str(file_path))
    total_pages = len(reader.pages)

    if max_pages is not None:
        total_pages = min(total_pages, max(0, max_pages))

    extracted_pages: list[ExtractedPdfPage] = []
    ocr_pages: list[int] = []
    ocr_errors: list[str] = []
    native_pages_count = 0
    ocr_pages_count = 0
    ocr_document: Any | None = None

    try:
        for page_index in range(total_pages):
            native_text = (reader.pages[page_index].extract_text() or "").strip()

            if _native_text_is_usable(native_text):
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
            except OcrUnavailableError as exc:
                ocr_errors.append(str(exc))
                ocr_text = ""

            if _meaningful_char_count(ocr_text) > _meaningful_char_count(
                native_text
            ):
                extracted_pages.append(
                    ExtractedPdfPage(page_index, ocr_text, "ocr")
                )
                ocr_pages.append(page_index + 1)
                ocr_pages_count += 1
            elif native_text:
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
