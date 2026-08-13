from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass

import numpy as np

from app.services.embedding_service import EmbeddingService


MIN_CHUNK_TOKENS = 400
TARGET_CHUNK_TOKENS = 550
MAX_CHUNK_TOKENS = 700
CHUNK_OVERLAP_TOKENS = 75
MIN_OVERLAP_TOKENS = 50
MAX_OVERLAP_TOKENS = 100

TABLE_CAPTION_RE = re.compile(
    r"\b(?:table|tab\.?|табл\.?|таблица|продолжение\s+табл)\b",
    re.IGNORECASE,
)
NUMBER_RE = re.compile(r"[-+]?\d+(?:[.,]\d+)?")
TOKEN_RE = re.compile(r"\w+|[^\w\s]", re.UNICODE)
SENTENCE_BOUNDARY_RE = re.compile(
    r"(?<=[.!?…])(?:[\"'»”\)\]]*)\s+(?=[\"'«“\(\[]*[A-ZА-ЯЁ0-9])"
)
CLAUSE_BOUNDARY_RE = re.compile(r"(?<=[;:])\s+")
ABBREVIATIONS = {
    "dr.",
    "fig.",
    "mr.",
    "mrs.",
    "prof.",
    "табл.",
    "рис.",
    "т.е.",
    "т.д.",
    "т.п.",
}


@dataclass(frozen=True, slots=True)
class SemanticSource:
    text: str
    page_number: int | None = None


@dataclass(frozen=True, slots=True)
class SemanticUnit:
    text: str
    page_number: int | None
    paragraph_index: int
    token_count: int


@dataclass(frozen=True, slots=True)
class SemanticChunk:
    text: str
    page_start: int | None
    page_end: int | None
    token_count: int


def looks_like_table_line(line: str) -> bool:
    line = " ".join(line.split())

    if not line:
        return True

    if TABLE_CAPTION_RE.search(line) and len(line) < 120:
        return True

    numbers = NUMBER_RE.findall(line)

    if len(numbers) < 6:
        return False

    non_space_chars = [char for char in line if not char.isspace()]

    if not non_space_chars:
        return True

    numeric_chars = sum(
        1
        for char in non_space_chars
        if char.isdigit() or char in ".,;:+-<>"
    )
    digit_ratio = numeric_chars / len(non_space_chars)
    words = re.findall(r"[A-Za-zА-Яа-яЁё]{3,}", line)

    if len(numbers) >= 10 and digit_ratio >= 0.35:
        return True

    return len(numbers) >= 6 and len(words) <= 4 and digit_ratio >= 0.45


def clean_text_for_semantic_chunking(text: str) -> str:
    lines: list[str] = []

    for raw_line in text.splitlines():
        line = raw_line.strip()

        if not line:
            if lines and lines[-1]:
                lines.append("")
            continue

        if looks_like_table_line(line):
            continue

        lines.append(line)

    cleaned = "\n".join(lines)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned.strip()


def estimate_token_count(text: str) -> int:
    """Fast tokenizer-independent fallback used by tests and light services."""

    return len(TOKEN_RE.findall(text))


def _count_tokens(text: str, embedding_service: EmbeddingService) -> int:
    counter = getattr(embedding_service, "count_tokens", None)

    if callable(counter):
        try:
            return max(1, int(counter(text)))
        except (AttributeError, TypeError, ValueError):
            pass

    return max(1, estimate_token_count(text))


def _split_sentences(paragraph: str) -> list[str]:
    boundaries: list[int] = []

    for match in SENTENCE_BOUNDARY_RE.finditer(paragraph):
        prefix = paragraph[: match.start()].rstrip()
        previous_token = prefix.rsplit(" ", 1)[-1].casefold()

        if previous_token in ABBREVIATIONS or re.fullmatch(r"[a-zа-яё]\.", previous_token):
            continue

        boundaries.append(match.end())

    if not boundaries:
        return [" ".join(paragraph.split())]

    sentences: list[str] = []
    start = 0

    for boundary in boundaries:
        sentence = " ".join(paragraph[start:boundary].split())
        if sentence:
            sentences.append(sentence)
        start = boundary

    tail = " ".join(paragraph[start:].split())
    if tail:
        sentences.append(tail)

    return sentences


def _split_oversized_text(
    text: str,
    embedding_service: EmbeddingService,
    max_tokens: int,
) -> list[str]:
    clauses = [part.strip() for part in CLAUSE_BOUNDARY_RE.split(text) if part.strip()]

    if len(clauses) == 1:
        clauses = TOKEN_RE.findall(text)

    parts: list[str] = []
    current: list[str] = []

    for clause in clauses:
        candidate = " ".join([*current, clause]).strip()

        if current and _count_tokens(candidate, embedding_service) > max_tokens:
            parts.append(" ".join(current).strip())
            current = []

        current.append(clause)

    if current:
        parts.append(" ".join(current).strip())

    return [part for part in parts if part]


def split_sources_to_units(
    sources: list[SemanticSource],
    embedding_service: EmbeddingService,
    *,
    max_tokens: int = MAX_CHUNK_TOKENS,
) -> list[SemanticUnit]:
    units: list[SemanticUnit] = []
    paragraph_index = 0

    for source in sources:
        cleaned = clean_text_for_semantic_chunking(source.text)

        if not cleaned:
            continue

        paragraphs = re.split(r"\n\s*\n+", cleaned)

        for paragraph in paragraphs:
            paragraph = " ".join(paragraph.split())

            if not paragraph:
                continue

            sentences = _split_sentences(paragraph)

            for sentence in sentences:
                pieces = (
                    _split_oversized_text(sentence, embedding_service, max_tokens)
                    if _count_tokens(sentence, embedding_service) > max_tokens
                    else [sentence]
                )

                for piece in pieces:
                    units.append(
                        SemanticUnit(
                            text=piece,
                            page_number=source.page_number,
                            paragraph_index=paragraph_index,
                            token_count=_count_tokens(piece, embedding_service),
                        )
                    )

            paragraph_index += 1

    return units


def split_text_to_units(text: str) -> list[str]:
    """Compatibility helper that exposes the sentence-level hierarchy."""

    class _FallbackCounter:
        @staticmethod
        def count_tokens(value: str) -> int:
            return estimate_token_count(value)

    return [
        unit.text
        for unit in split_sources_to_units(
            [SemanticSource(text=text)],
            _FallbackCounter(),  # type: ignore[arg-type]
        )
    ]


def cosine_similarity(a: list[float], b: list[float]) -> float:
    a_array = np.asarray(a, dtype=float)
    b_array = np.asarray(b, dtype=float)
    denominator = np.linalg.norm(a_array) * np.linalg.norm(b_array)

    if denominator == 0:
        return 0.0

    return float(np.dot(a_array, b_array) / denominator)


def _tokens_between(prefix_tokens: list[int], start: int, end: int) -> int:
    return prefix_tokens[end] - prefix_tokens[start]


def _choose_chunk_end(
    units: list[SemanticUnit],
    similarities: list[float],
    prefix_tokens: list[int],
    start: int,
    *,
    min_tokens: int,
    target_tokens: int,
    max_tokens: int,
) -> int:
    hard_end = start

    while (
        hard_end < len(units)
        and _tokens_between(prefix_tokens, start, hard_end + 1) <= max_tokens
    ):
        hard_end += 1

    if hard_end == start:
        return min(start + 1, len(units))

    if hard_end == len(units):
        return hard_end

    candidates = [
        end
        for end in range(start + 1, hard_end + 1)
        if _tokens_between(prefix_tokens, start, end) >= min_tokens
    ]

    if not candidates:
        return hard_end

    def boundary_score(end: int) -> float:
        token_count = _tokens_between(prefix_tokens, start, end)
        target_distance = abs(token_count - target_tokens) / max(1, target_tokens)
        paragraph_boundary = (
            0.45
            if end == len(units)
            or units[end - 1].paragraph_index != units[end].paragraph_index
            else 0.0
        )
        semantic_boundary = 0.0

        if end - 1 < len(similarities):
            semantic_boundary = max(0.0, 1.0 - similarities[end - 1]) * 0.35

        return paragraph_boundary + semantic_boundary - target_distance * 0.35

    chosen = max(candidates, key=boundary_score)
    remaining_tokens = _tokens_between(prefix_tokens, chosen, len(units))
    all_tokens = _tokens_between(prefix_tokens, start, len(units))

    if remaining_tokens < min_tokens - MIN_OVERLAP_TOKENS and all_tokens <= max_tokens:
        return len(units)

    return chosen


def _find_overlap_start(
    units: list[SemanticUnit],
    chunk_start: int,
    chunk_end: int,
    overlap_tokens: int,
) -> int:
    overlap_start = chunk_end
    accumulated = 0

    while overlap_start > chunk_start:
        candidate_tokens = units[overlap_start - 1].token_count

        if (
            accumulated >= MIN_OVERLAP_TOKENS
            and accumulated + candidate_tokens > MAX_OVERLAP_TOKENS
        ):
            break

        overlap_start -= 1
        accumulated += candidate_tokens

        if accumulated >= overlap_tokens:
            break

    if overlap_start == chunk_start and chunk_end < len(units):
        return max(chunk_start + 1, chunk_end - 1)

    return overlap_start


def _join_units(units: list[SemanticUnit]) -> str:
    parts: list[str] = []

    for index, unit in enumerate(units):
        if index and unit.paragraph_index != units[index - 1].paragraph_index:
            parts.append("\n\n")
        elif index:
            parts.append(" ")

        parts.append(unit.text)

    return "".join(parts).strip()


async def split_sources_into_semantic_chunks(
    sources: list[SemanticSource],
    embedding_service: EmbeddingService,
    *,
    min_chunk_tokens: int = MIN_CHUNK_TOKENS,
    target_chunk_tokens: int = TARGET_CHUNK_TOKENS,
    max_chunk_tokens: int = MAX_CHUNK_TOKENS,
    overlap_tokens: int = CHUNK_OVERLAP_TOKENS,
) -> list[SemanticChunk]:
    if not 0 < min_chunk_tokens <= target_chunk_tokens <= max_chunk_tokens:
        raise ValueError("Chunk token limits must satisfy 0 < min <= target <= max")

    units = split_sources_to_units(
        sources,
        embedding_service,
        max_tokens=max_chunk_tokens,
    )

    if not units:
        return []

    if len(units) == 1:
        unit = units[0]
        return [
            SemanticChunk(
                text=unit.text,
                page_start=unit.page_number,
                page_end=unit.page_number,
                token_count=unit.token_count,
            )
        ]

    unit_embeddings = await asyncio.to_thread(
        embedding_service.embed_documents,
        [unit.text for unit in units],
    )
    similarities = [
        cosine_similarity(unit_embeddings[index], unit_embeddings[index + 1])
        for index in range(len(unit_embeddings) - 1)
    ]
    prefix_tokens = [0]

    for unit in units:
        prefix_tokens.append(prefix_tokens[-1] + unit.token_count)

    chunks: list[SemanticChunk] = []
    start = 0

    while start < len(units):
        end = _choose_chunk_end(
            units,
            similarities,
            prefix_tokens,
            start,
            min_tokens=min_chunk_tokens,
            target_tokens=target_chunk_tokens,
            max_tokens=max_chunk_tokens,
        )

        # Avoid producing a tiny final fragment. Move the preceding boundary
        # backwards until the remaining tail (including overlap) reaches the
        # requested minimum, while keeping the current chunk meaningful.
        if end < len(units):
            next_start = _find_overlap_start(units, start, end, overlap_tokens)
            tail_tokens = _tokens_between(prefix_tokens, next_start, len(units))

            while tail_tokens < min_chunk_tokens and end > start + 1:
                candidate_end = end - 1
                candidate_tokens = _tokens_between(prefix_tokens, start, candidate_end)

                if candidate_tokens < min_chunk_tokens:
                    break

                end = candidate_end
                next_start = _find_overlap_start(units, start, end, overlap_tokens)
                tail_tokens = _tokens_between(prefix_tokens, next_start, len(units))

        chunk_units = units[start:end]
        page_numbers = [
            unit.page_number for unit in chunk_units if unit.page_number is not None
        ]
        chunks.append(
            SemanticChunk(
                text=_join_units(chunk_units),
                page_start=min(page_numbers) if page_numbers else None,
                page_end=max(page_numbers) if page_numbers else None,
                token_count=sum(unit.token_count for unit in chunk_units),
            )
        )

        if end >= len(units):
            break

        start = _find_overlap_start(units, start, end, overlap_tokens)

    return chunks


async def split_text_into_semantic_chunks(
    text: str,
    embedding_service: EmbeddingService,
    *,
    min_chunk_tokens: int = MIN_CHUNK_TOKENS,
    target_chunk_tokens: int = TARGET_CHUNK_TOKENS,
    max_chunk_tokens: int = MAX_CHUNK_TOKENS,
    overlap_tokens: int = CHUNK_OVERLAP_TOKENS,
) -> list[str]:
    chunks = await split_sources_into_semantic_chunks(
        [SemanticSource(text=text)],
        embedding_service,
        min_chunk_tokens=min_chunk_tokens,
        target_chunk_tokens=target_chunk_tokens,
        max_chunk_tokens=max_chunk_tokens,
        overlap_tokens=overlap_tokens,
    )
    return [chunk.text for chunk in chunks]
