import asyncio
import re
from dataclasses import dataclass

import numpy as np

from app.services.embedding_service import EmbeddingService


@dataclass
class SemanticChunk:
    text: str


TABLE_CAPTION_RE = re.compile(
    r"\b(?:table|tab\.?|табл\.?|таблица|продолжение\s+табл)\b",
    re.IGNORECASE,
)
NUMBER_RE = re.compile(r"[-+]?\d+(?:[.,]\d+)?")
SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?…])\s+(?=[A-ZА-ЯЁ])")


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

    if len(numbers) >= 6 and len(words) <= 4 and digit_ratio >= 0.45:
        return True

    return False


def clean_text_for_semantic_chunking(text: str) -> str:
    lines: list[str] = []

    for raw_line in text.splitlines():
        line = raw_line.strip()

        if not line:
            lines.append("")
            continue

        if looks_like_table_line(line):
            continue

        lines.append(line)

    cleaned = "\n".join(lines)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned.strip()


def split_long_unit(text: str, *, target_chars: int = 650) -> list[str]:
    sentences = SENTENCE_SPLIT_RE.split(text)

    if len(sentences) == 1:
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        sentences = lines if len(lines) > 1 else sentences

    units: list[str] = []
    current_parts: list[str] = []
    current_length = 0

    for sentence in sentences:
        sentence = " ".join(sentence.split())

        if not sentence:
            continue

        if current_parts and current_length + len(sentence) > target_chars:
            units.append(" ".join(current_parts).strip())
            current_parts = []
            current_length = 0

        current_parts.append(sentence)
        current_length += len(sentence) + 1

    if current_parts:
        units.append(" ".join(current_parts).strip())

    return [unit for unit in units if len(unit) >= 50]


def split_text_to_units(text: str) -> list[str]:
    """
    Делит текст на базовые смысловые единицы.
    Для PDF лучше начинать с абзацев/блоков, а не с отдельных предложений.
    """
    text = clean_text_for_semantic_chunking(text)

    if not text:
        return []

    blocks = re.split(r"\n\s*\n+", text)

    units: list[str] = []

    for block in blocks:
        block = block.strip()

        if len(block) < 50:
            continue

        if len(block) > 850:
            units.extend(split_long_unit(block))
            continue

        units.append(" ".join(block.split()))

    return units


def cosine_similarity(a: list[float], b: list[float]) -> float:
    a_array = np.array(a)
    b_array = np.array(b)

    denominator = np.linalg.norm(a_array) * np.linalg.norm(b_array)

    if denominator == 0:
        return 0.0

    return float(np.dot(a_array, b_array) / denominator)


async def split_text_into_semantic_chunks(
    text: str,
    embedding_service: EmbeddingService,
    *,
    min_chunk_chars: int = 450,
    max_chunk_chars: int = 1400,
    similarity_threshold: float = 0.55,
) -> list[str]:
    units = split_text_to_units(text)

    if not units:
        return []

    if len(units) == 1:
        return units

    unit_embeddings = await asyncio.to_thread(
        embedding_service.embed_texts,
        units,
    )

    chunks: list[str] = []
    current_parts: list[str] = []
    current_length = 0

    for index, unit in enumerate(units):
        current_parts.append(unit)
        current_length += len(unit)

        is_last_unit = index == len(units) - 1

        if is_last_unit:
            chunks.append("\n\n".join(current_parts))
            break

        similarity = cosine_similarity(
            unit_embeddings[index],
            unit_embeddings[index + 1],
        )

        should_split_by_semantics = (
            similarity < similarity_threshold
            and current_length >= min_chunk_chars
        )

        should_split_by_size = current_length >= max_chunk_chars

        if should_split_by_semantics or should_split_by_size:
            chunks.append("\n\n".join(current_parts))
            current_parts = []
            current_length = 0

    return chunks
