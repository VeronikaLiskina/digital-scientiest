import re
from functools import lru_cache

import pymorphy3


TOKEN_RE = re.compile(r"[A-Za-zА-Яа-яЁё0-9]+")

STOPWORDS = {
    "а",
    "без",
    "был",
    "быть",
    "в",
    "во",
    "где",
    "для",
    "до",
    "его",
    "ее",
    "есть",
    "и",
    "из",
    "или",
    "их",
    "как",
    "какие",
    "какой",
    "к",
    "ко",
    "на",
    "не",
    "о",
    "об",
    "от",
    "по",
    "при",
    "про",
    "публикация",
    "материал",
    "источник",
    "информация",
    "фрагмент",
    "ответ",
    "тема",
    "исследование",
    "работа",
    "с",
    "со",
    "у",
    "что",
    "это",
    "the",
    "a",
    "an",
    "and",
    "are",
    "for",
    "from",
    "in",
    "is",
    "of",
    "on",
    "or",
    "to",
    "what",
    "which",
    "with",
}

MIN_DIRECT_TOKEN_COVERAGE = 0.25
MIN_SHORT_QUERY_PARTIAL_SIMILARITY = 0.72
MIN_LONG_QUERY_PARTIAL_SIMILARITY = 0.70
HIGH_SEMANTIC_SIMILARITY = 0.78
MIN_SHARED_PREFIX_LENGTH = 6
MIN_SHARED_PREFIX_RATIO = 0.75


@lru_cache(maxsize=1)
def _get_morph() -> pymorphy3.MorphAnalyzer:
    return pymorphy3.MorphAnalyzer()


def _normalize_token(token: str) -> str:
    normalized = token.lower().replace("ё", "е")

    if re.search(r"[а-я]", normalized):
        return _get_morph().parse(normalized)[0].normal_form.replace("ё", "е")

    return normalized


def extract_relevance_tokens(text: str) -> set[str]:
    tokens: set[str] = set()

    for raw_token in TOKEN_RE.findall(text):
        token = _normalize_token(raw_token)

        if len(token) < 4 or token in STOPWORDS:
            continue

        tokens.add(token)

    return tokens


def _chunk_text(chunk: dict) -> str:
    return " ".join(
        [
            str(chunk.get("publication_title") or ""),
            str(chunk.get("text") or ""),
        ]
    )


def _tokens_match(left: str, right: str) -> bool:
    if left == right:
        return True

    if min(len(left), len(right)) < 5:
        return False

    if left.startswith(right) or right.startswith(left):
        return True

    shared_prefix_length = 0
    for left_char, right_char in zip(left, right):
        if left_char != right_char:
            break

        shared_prefix_length += 1

    return (
        shared_prefix_length >= MIN_SHARED_PREFIX_LENGTH
        and shared_prefix_length / min(len(left), len(right)) >= MIN_SHARED_PREFIX_RATIO
    )


def _matching_question_tokens(
    question_tokens: set[str],
    source_tokens: set[str],
) -> set[str]:
    return {
        question_token
        for question_token in question_tokens
        if any(
            _tokens_match(question_token, source_token)
            for source_token in source_tokens
        )
    }


def is_relevant_source(question: str, chunk: dict) -> bool:
    similarity = float(chunk.get("similarity") or 0)

    if similarity >= HIGH_SEMANTIC_SIMILARITY:
        return True

    question_tokens = extract_relevance_tokens(question)

    if not question_tokens:
        return similarity >= 0.7

    source_tokens = extract_relevance_tokens(_chunk_text(chunk))
    overlap = _matching_question_tokens(question_tokens, source_tokens)
    coverage = len(overlap) / len(question_tokens)

    if not overlap:
        return False

    if len(question_tokens) <= 2:
        if coverage >= 1:
            return True

        return similarity >= MIN_SHORT_QUERY_PARTIAL_SIMILARITY

    if coverage >= MIN_DIRECT_TOKEN_COVERAGE:
        return True

    return similarity >= MIN_LONG_QUERY_PARTIAL_SIMILARITY


def filter_relevant_sources(
    question: str,
    chunks: list[dict],
    limit: int,
) -> list[dict]:
    relevant_chunks = [
        chunk for chunk in chunks if is_relevant_source(question, chunk)
    ]

    return relevant_chunks[:limit]


def select_answer_sources(
    question: str,
    chunks: list[dict],
    limit: int,
) -> list[dict]:
    relevant_chunks = filter_relevant_sources(
        question=question,
        chunks=chunks,
        limit=limit,
    )

    if relevant_chunks:
        return relevant_chunks

    return chunks[:limit]
