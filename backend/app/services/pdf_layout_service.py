"""Locate article headings using native PDF or OCR line geometry."""
from collections import defaultdict
from dataclasses import dataclass
from statistics import median
import re

from app.utils.text_quality import is_readable_text

try:
    import pymupdf
except ImportError:  # Native text parsing remains available without rendering.
    pymupdf = None


SERVICE_RE = re.compile(
    r"(?:\b(?:issn|isbn|doi|copyright|journal|homepage|university|institute|department)\b|"
    r"\b(?:vol\.?|v\s+ol\.?|volume|no\.?|pp\.)\s*\d|"
    r"geological society|contents lists|check for updates|https?://|@)", re.I,
)
LABEL_RE = re.compile(
    r"^(?:minerals|article|research article|geology|geochemistry|petrology|"
    r"doklady earth sciences|earth.science reviews|abstract|аннотация|"
    r"references|литература|содержание|геология|геохимия)\s*$", re.I,
)
AUTHOR_LINE_START_RE = re.compile(
    r"^(?:(?:[A-Z][a-z'’\-]+\s+)?[A-Z]\.\s*(?:[A-Z]\.\s*)?[A-Z][a-z'’\-]+|"
    r"[А-ЯЁ]\.\s*[А-ЯЁ]\.\s*[А-ЯЁ][а-яё-]+)(?:\s|[,;*]|$)"
)


@dataclass(frozen=True)
class LayoutLine:
    text: str
    x0: float
    y0: float
    x1: float
    y1: float
    size: float
    confidence: float = 100


def title_from_lines(lines: list[LayoutLine]) -> str | None:
    """Require a prominent, readable block in the upper part of the page."""
    body_sizes = [line.size for line in lines if .3 < line.y0 < .9 and len(line.text) > 35]
    if not body_sizes:
        body_sizes = [line.size for line in lines if len(line.text) > 15]
    if not body_sizes:
        return None
    body_size = median(body_sizes)
    candidates: list[list[LayoutLine]] = []
    group: list[LayoutLine] = []
    for line in sorted(lines, key=lambda item: (item.y0, item.x0)):
        text = re.sub(r"\s+[®@](?:\s.*|[-—–]+.*)$", "", line.text).lstrip(" ,‚").rstrip()
        eligible = (
            .08 <= line.y0 <= .48 and line.confidence >= 45
            and line.size >= body_size * 1.15
            and not SERVICE_RE.search(text) and not LABEL_RE.fullmatch(text)
            and not AUTHOR_LINE_START_RE.search(text)
            and is_readable_text(text, strict=True)
        )
        if not eligible:
            if group:
                candidates.append(group)
                group = []
            continue
        cleaned = LayoutLine(text, line.x0, line.y0, line.x1, line.y1, line.size, line.confidence)
        if group:
            last = group[-1]
            adjacent = (
                line.y0 - last.y1 < max(last.size, line.size) * 1.7
                and min(last.size, line.size) / max(last.size, line.size) > .78
                and (abs(line.x0 - last.x0) < .15 or abs((line.x0 + line.x1) - (last.x0 + last.x1)) < .3)
            )
            if not adjacent:
                candidates.append(group)
                group = []
        group.append(cleaned)
    if group:
        candidates.append(group)
    ranked = []
    for block in candidates:
        text = re.sub(r"\s+", " ", " ".join(line.text for line in block)).strip()
        if not 15 <= len(text) <= 450 or len(text.split()) < 3:
            continue
        score = median(line.size for line in block) / body_size + min(len(text.split()), 14) / 14
        ranked.append((score, -block[0].y0, text))
    return max(ranked)[2] if ranked else None


@dataclass(frozen=True)
class NativePageMetadata:
    title: str | None
    author_lines: list[str]


def clean_author_spans(spans: list[dict]) -> str:
    largest = max((span["size"] for span in spans), default=0)
    return "".join(span["text"] for span in spans if not (
        span["text"].strip() and re.fullmatch(r"[a-z0-9,; *†‡]+", span["text"])
        and (span.get("flags", 0) & 1 or span["size"] < largest * .85)
    )).strip()


def native_page_metadata(file_path, page_indexes: set[int]) -> dict[int, NativePageMetadata]:
    if pymupdf is None or not page_indexes:
        return {}
    metadata = {}
    try:
        with pymupdf.open(str(file_path)) as document:
            for index in sorted(page_indexes):
                page = document[index]
                lines = []
                author_lines = []
                for block in page.get_text("dict")["blocks"]:
                    for line in block.get("lines", []):
                        spans = line["spans"]
                        if not spans:
                            continue
                        x0, y0, x1, y1 = line["bbox"]
                        cleaned = clean_author_spans(spans)
                        if cleaned:
                            author_lines.append((y0, x0, cleaned))
                        lines.append(LayoutLine(
                            "".join(span["text"] for span in spans),
                            x0 / page.rect.width, y0 / page.rect.height,
                            x1 / page.rect.width, y1 / page.rect.height,
                            max(span["size"] for span in spans) / page.rect.height,
                        ))
                title = title_from_lines(lines)
                metadata[index] = NativePageMetadata(title, [text for _, _, text in sorted(author_lines)])
    except (RuntimeError, ValueError, OSError):
        # The text/OCR path still works when layout inspection fails.
        return metadata
    return metadata


class OCRText(str):
    """Keep geometry-derived heading alongside the ordinary recognized text."""
    def __new__(cls, text: str, layout_title: str | None = None):
        value = super().__new__(cls, text)
        value.layout_title = layout_title
        return value


def text_from_ocr_data(data: dict, width: int, height: int) -> OCRText:
    groups = defaultdict(list)
    for index, text in enumerate(data["text"]):
        if text.strip() and float(data["conf"][index]) >= 0:
            key = (data["block_num"][index], data["par_num"][index], data["line_num"][index])
            groups[key].append(index)
    lines = []
    for indexes in groups.values():
        text = " ".join(data["text"][index].strip() for index in indexes)
        x0 = min(data["left"][index] for index in indexes)
        y0 = min(data["top"][index] for index in indexes)
        x1 = max(data["left"][index] + data["width"][index] for index in indexes)
        y1 = max(data["top"][index] + data["height"][index] for index in indexes)
        lines.append(LayoutLine(
            text, x0 / width, y0 / height, x1 / width, y1 / height,
            median(data["height"][index] for index in indexes) / height,
            sum(float(data["conf"][index]) for index in indexes) / len(indexes),
        ))
    return OCRText("\n".join(line.text for line in lines), title_from_lines(lines))
