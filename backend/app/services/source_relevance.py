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
MIN_SEMANTIC_SUPPLEMENT_SIMILARITY = 0.70
MIN_CROSS_LANGUAGE_SIMILARITY = 0.65
CROSS_LANGUAGE_RANK_BOOST = 0.03
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


def _dominant_script(text: str) -> str | None:
    cyrillic_count = len(re.findall(r"[А-Яа-яЁё]", text))
    latin_count = len(re.findall(r"[A-Za-z]", text))

    if cyrillic_count > latin_count:
        return "cyrillic"
    if latin_count > cyrillic_count:
        return "latin"
    return None


def _is_cross_language_source(question: str, chunk: dict) -> bool:
    question_script = _dominant_script(question)
    source_script = _dominant_script(
        str(chunk.get("text") or chunk.get("publication_title") or "")
    )

    return (
        question_script is not None
        and source_script is not None
        and question_script != source_script
    )


def _candidate_rank_score(question: str, chunk: dict) -> float:
    similarity = float(chunk.get("similarity") or 0)
    if (
        similarity >= MIN_CROSS_LANGUAGE_SIMILARITY
        and _is_cross_language_source(question, chunk)
    ):
        return similarity + CROSS_LANGUAGE_RANK_BOOST
    return similarity


def _promote_cross_language_candidates(
    question: str,
    candidates: list[dict],
) -> list[dict]:
    """Promote only cross-language matches while preserving all other ordering."""
    ranked: list[dict] = []

    for chunk in candidates:
        if not (
            float(chunk.get("similarity") or 0)
            >= MIN_CROSS_LANGUAGE_SIMILARITY
            and _is_cross_language_source(question, chunk)
        ):
            ranked.append(chunk)
            continue

        rank_score = _candidate_rank_score(question, chunk)
        insert_at = len(ranked)
        for index, existing in enumerate(ranked):
            if _candidate_rank_score(question, existing) < rank_score:
                insert_at = index
                break

        ranked.insert(insert_at, chunk)

    return ranked


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


def diversify_chunks_by_publication(
    chunks: list[dict],
    limit: int,
) -> list[dict]:
    """Prefer one best-ranked chunk per publication, then fill spare slots."""
    selected_indices: set[int] = set()
    seen_publications: set[int] = set()
    selected: list[dict] = []

    for index, chunk in enumerate(chunks):
        publication_id = chunk.get("publication_id")

        # Chunks without publication metadata are treated as independent. This
        # keeps the helper safe for diagnostics and older stored data.
        if publication_id is not None and publication_id in seen_publications:
            continue

        selected.append(chunk)
        selected_indices.add(index)
        if publication_id is not None:
            seen_publications.add(publication_id)

        if len(selected) >= limit:
            return selected

    for index, chunk in enumerate(chunks):
        if index in selected_indices:
            continue

        selected.append(chunk)
        if len(selected) >= limit:
            break

    return selected


def select_answer_sources(
    question: str,
    chunks: list[dict],
    limit: int,
) -> list[dict]:
    relevant_chunks = filter_relevant_sources(
        question=question,
        chunks=chunks,
        limit=len(chunks),
    )

    if relevant_chunks:
        relevant_chunk_ids = {id(chunk) for chunk in relevant_chunks}
        candidates = [
            chunk
            for chunk in chunks
            if id(chunk) in relevant_chunk_ids
            or float(chunk.get("similarity") or 0)
            >= MIN_SEMANTIC_SUPPLEMENT_SIMILARITY
            or (
                float(chunk.get("similarity") or 0)
                >= MIN_CROSS_LANGUAGE_SIMILARITY
                and _is_cross_language_source(question, chunk)
            )
        ]
    else:
        candidates = chunks

    candidates = _promote_cross_language_candidates(question, candidates)

    return diversify_chunks_by_publication(candidates, limit)
