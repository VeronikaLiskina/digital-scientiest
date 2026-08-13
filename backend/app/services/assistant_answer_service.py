import json
import math
import re
from typing import Any

from app.services.local_llm_service import OllamaGenerationError


JSON_FENCE_RE = re.compile(r"^```(?:json)?\s*(.*?)\s*```$", re.DOTALL | re.IGNORECASE)
CYRILLIC_RE = re.compile(r"[А-Яа-яЁё]")
LATIN_RE = re.compile(r"[A-Za-z]")
CONTROL_CHARACTER_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
REPEATED_NOISE_RE = re.compile(r"([^\w\s])\1{3,}", re.UNICODE)
REPEATED_ALPHANUMERIC_RE = re.compile(r"([A-Za-zА-Яа-яЁё0-9])\1{5,}")
MIXED_SCRIPT_WORD_RE = re.compile(
    r"(?<![A-Za-zА-Яа-яЁё])"
    r"(?=[A-Za-zА-Яа-яЁё]*[A-Za-z])"
    r"(?=[A-Za-zА-Яа-яЁё]*[А-Яа-яЁё])"
    r"[A-Za-zА-Яа-яЁё]{2,}"
    r"(?![A-Za-zА-Яа-яЁё])"
)
BIBLIOGRAPHIC_ANSWER_RE = re.compile(
    r"(?:для\s+(?:более\s+)?детал\w*.*?\bсм\.?\s+"
    r"(?:в\s+)?(?:следующ\w+\s+)?источник|"
    r"(?:список\s+литературы|литература|references|bibliography)\s*:|"
    r"(?:подробнее|дополнительно)\s+см\.)",
    re.IGNORECASE | re.DOTALL,
)
BIBLIOGRAPHY_QUESTION_RE = re.compile(
    r"(?:\bавтор\w*\b|\bлитератур\w*\b|\bбиблиограф\w*\b|"
    r"\bкто\s+(?:изучал|исследовал|описал)\b|\bauthors?\b|"
    r"\breferences?\b|\bbibliograph\w*\b)",
    re.IGNORECASE,
)
UNNECESSARY_PREAMBLE_RE = re.compile(
    r"^\s*(?:вот\s+(?:ответ|что)|"
    r"согласно\s+(?:контексту|фрагменту|источнику|публикации)|"
    r"в\s+(?:найденном\s+)?(?:фрагменте|источнике|публикации)\s+"
    r"(?:говорится|описано|указано)|"
    r"на\s+основании\s+(?:контекста|фрагмента|источника)|"
    r"according\s+to\s+(?:the\s+)?(?:context|source|fragment)|"
    r"the\s+(?:source|fragment)\s+(?:says|states))",
    re.IGNORECASE,
)
SERVICE_MARKER_RE = re.compile(
    r"(?:source[_\s-]*id|chunk[_\s-]*id|chunk-\d+|"
    r"\bID\s+(?:публикации|фрагмента)\b|индекс\s+фрагмента|"
    r"(?:similarity|сходство)\s*:|retrieved_context|"
    r'"(?:blocks|kind|text|source_ids)"\s*:)',
    re.IGNORECASE,
)
MAX_ANSWER_BLOCKS = 30
MAX_BLOCK_TEXT_LENGTH = 5000
MAX_TOTAL_ANSWER_LENGTH = 10000


def _strip_optional_json_fence(raw_answer: str) -> str:
    stripped = raw_answer.strip()
    match = JSON_FENCE_RE.fullmatch(stripped)
    return match.group(1).strip() if match else stripped


def parse_structured_rag_answer(
    raw_answer: str,
    *,
    allowed_source_ids: set[str],
) -> list[dict[str, Any]]:
    try:
        payload = json.loads(_strip_optional_json_fence(raw_answer))
    except (TypeError, json.JSONDecodeError) as exc:
        raise OllamaGenerationError(
            "Модель вернула ответ не в структурированном JSON-формате"
        ) from exc

    if not isinstance(payload, dict) or set(payload) != {"blocks"}:
        raise OllamaGenerationError("Структура ответа модели содержит недопустимые поля")

    raw_blocks = payload["blocks"]
    if (
        not isinstance(raw_blocks, list)
        or not raw_blocks
        or len(raw_blocks) > MAX_ANSWER_BLOCKS
    ):
        raise OllamaGenerationError("Модель вернула некорректный список блоков ответа")

    blocks: list[dict[str, Any]] = []
    total_text_length = 0

    for raw_block in raw_blocks:
        if not isinstance(raw_block, dict) or set(raw_block) != {
            "kind",
            "text",
            "source_ids",
        }:
            raise OllamaGenerationError("Блок ответа модели содержит недопустимые поля")

        kind = raw_block["kind"]
        text = raw_block["text"]
        raw_source_ids = raw_block["source_ids"]
        if kind not in {"answer", "insufficient"}:
            raise OllamaGenerationError("Блок ответа модели содержит неизвестный тип")
        if not isinstance(text, str) or not text.strip():
            raise OllamaGenerationError("Модель вернула пустой текстовый блок")
        text = text.strip()
        if len(text) > MAX_BLOCK_TEXT_LENGTH:
            raise OllamaGenerationError("Текстовый блок модели превышает допустимый размер")

        if not isinstance(raw_source_ids, list):
            raise OllamaGenerationError("source_ids блока ответа должен быть списком")
        if kind == "answer" and not raw_source_ids:
            raise OllamaGenerationError("Содержательный блок модели не содержит source_id")
        if kind == "insufficient" and raw_source_ids:
            raise OllamaGenerationError(
                "Блок о недостатке информации не должен содержать source_id"
            )

        source_ids: list[str] = []
        for source_id in raw_source_ids:
            if not isinstance(source_id, str) or source_id not in allowed_source_ids:
                raise OllamaGenerationError(
                    "Модель сослалась на несуществующий или недопустимый source_id"
                )
            if source_id not in source_ids:
                source_ids.append(source_id)

        total_text_length += len(text)
        if total_text_length > MAX_TOTAL_ANSWER_LENGTH:
            raise OllamaGenerationError("Ответ модели превышает допустимый размер")

        blocks.append({"text": text, "source_ids": source_ids})

    return blocks


def answer_text_from_blocks(blocks: list[dict[str, Any]]) -> str:
    return "\n\n".join(str(block["text"]) for block in blocks)


def validate_human_answer(
    blocks: list[dict[str, Any]],
    *,
    expected_language: str,
    allow_bibliography: bool = False,
) -> None:
    text = answer_text_from_blocks(blocks)

    if (
        "\ufffd" in text
        or CONTROL_CHARACTER_RE.search(text)
        or REPEATED_NOISE_RE.search(text)
        or REPEATED_ALPHANUMERIC_RE.search(text)
    ):
        raise OllamaGenerationError("Текст ответа содержит повреждённые или лишние символы")

    if SERVICE_MARKER_RE.search(text):
        raise OllamaGenerationError("Текст ответа содержит служебные данные RAG")

    if MIXED_SCRIPT_WORD_RE.search(text):
        raise OllamaGenerationError(
            "Текст ответа содержит OCR-слово со смешением кириллицы и латиницы"
        )

    if not allow_bibliography and BIBLIOGRAPHIC_ANSWER_RE.search(text):
        raise OllamaGenerationError(
            "Ответ содержит не запрошенный пользователем список литературы"
        )

    if any(
        UNNECESSARY_PREAMBLE_RE.search(str(block["text"]))
        for block in blocks
    ):
        raise OllamaGenerationError("Текст ответа содержит лишнее служебное вступление")

    letters_count = sum(character.isalpha() for character in text)
    visible_count = sum(not character.isspace() for character in text)
    if letters_count < 3 or letters_count < visible_count * 0.35:
        raise OllamaGenerationError("Текст ответа не похож на связный человеческий ответ")

    cyrillic_count = len(CYRILLIC_RE.findall(text))
    latin_count = len(LATIN_RE.findall(text))

    if expected_language == "ru":
        if cyrillic_count == 0 or latin_count > max(12, cyrillic_count * 0.2):
            raise OllamaGenerationError("Модель вернула ответ не на русском языке")
    elif expected_language == "en":
        if latin_count == 0 or cyrillic_count > max(12, latin_count * 0.2):
            raise OllamaGenerationError("Модель вернула ответ не на английском языке")


def validate_source_coverage(
    blocks: list[dict[str, Any]],
    *,
    allowed_source_ids: set[str],
    detail_percent: int = 80,
) -> None:
    """Require a substantive answer to cover the requested share of RAG sources."""

    if not 0 <= detail_percent <= 100:
        raise ValueError("detail_percent должен находиться в диапазоне от 0 до 100")
    if not allowed_source_ids:
        return

    used_source_ids = {
        source_id
        for block in blocks
        for source_id in block.get("source_ids", [])
        if source_id in allowed_source_ids
    }
    # An answer with no citations is an explicit `insufficient` response. It must
    # remain possible when the retrieved context cannot answer the question.
    if not used_source_ids:
        return

    required_source_count = math.ceil(
        len(allowed_source_ids) * detail_percent / 100
    )
    if len(used_source_ids) < required_source_count:
        raise OllamaGenerationError(
            "Ответ использует недостаточно релевантных источников: "
            f"требуется не менее {detail_percent}% "
            f"({required_source_count} из {len(allowed_source_ids)})"
        )


def single_answer_block(text: str) -> list[dict[str, Any]]:
    return [{"text": text, "source_ids": []}]


def question_requests_bibliography(question: str) -> bool:
    return BIBLIOGRAPHY_QUESTION_RE.search(question) is not None
