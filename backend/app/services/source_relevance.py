import re
from dataclasses import dataclass
from functools import lru_cache

import pymorphy3

from app.services.scientific_query_expansion import (
    contains_geochronology_method_evidence,
    is_geochronology_method_query,
)


TOKEN_RE = re.compile(r"[A-Za-zА-Яа-яЁё0-9]+")
FIGURE_OR_TABLE_CAPTION_RE = re.compile(
    r"^\s*(?:рис(?:\.|унок\b)|fig(?:\.|ure\b)|табл(?:\.|ица\b)|table\b)",
    re.IGNORECASE,
)
SOURCE_LOOKUP_INTENT_RE = re.compile(
    r"(?:упомин\w*|публикаци\w*|источник\w*|в\s+каких\s+работ\w*)",
    re.IGNORECASE,
)
DEFINITION_INTENT_RE = re.compile(
    r"(?:что\s+(?:это|такое)|что\s+представля\w*|определени\w*)",
    re.IGNORECASE,
)

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
    "каков",
    "каковой",
    "какие",
    "какой",
    "когда",
    "который",
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
    "упоминаться",
    "упоминать",
    "упомянуть",
    "почему",
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
    "сколько",
    "зачем",
    "это",
    "такой",
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

LOW_INFORMATION_TOKENS = {
    "геологический",
    "строение",
    "территория",
    "регион",
    "участок",
    "рассматривать",
    "описать",
    "характеристика",
    "особенность",
    "данные",
    "результат",
    "general",
    "geological",
    "geology",
    "region",
    "study",
}
LOW_INFORMATION_TOKEN_WEIGHT = 0.35
MIN_SHORT_QUERY_COVERAGE = 1.0
MIN_LONG_QUERY_COVERAGE = 0.55
MIN_STRONG_SEMANTIC_SIMILARITY = 0.78
MIN_STRONG_SEMANTIC_COVERAGE = 0.45
MAX_ANSWER_SOURCES = 8
MIN_CROSS_LANGUAGE_SIMILARITY = 0.85
MIN_CROSS_LANGUAGE_MARGIN = 0.04
MIN_STRONG_MULTITOKEN_SIMILARITY = 0.85
MIN_STRONG_MULTITOKEN_COVERAGE = 0.35
MIN_SHARED_PREFIX_LENGTH = 6
MIN_SHARED_PREFIX_RATIO = 0.75


@dataclass(frozen=True, slots=True)
class SourceRelevanceScore:
    chunk: dict
    similarity: float
    text_coverage: float
    title_coverage: float
    matched_text_tokens: frozenset[str]
    question_tokens: frozenset[str]
    specific_question_tokens: frozenset[str]
    matched_specific_tokens: frozenset[str]
    matched_cross_language_tokens: frozenset[str]
    required_text_coverage: float
    cross_language_coverage: float
    is_cross_language: bool
    is_caption: bool
    generic_high_confidence_match: bool
    strong_multitoken_match: bool
    direct_geochronology_method_evidence: bool
    is_directly_relevant: bool
    is_cross_language_relevant: bool
    score: float
    is_relevant: bool


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


def build_entity_intent_reranker_query(question: str) -> tuple[str, str] | None:
    """Return a focused entity query and intent for safe short-query reranking.

    Meta wording such as "where is X mentioned" controls answer formatting,
    not passage relevance. The entity itself remains mandatory because this
    helper only activates when exactly one relevance token survives.
    """
    relevance_tokens = extract_relevance_tokens(question)
    if len(relevance_tokens) != 1:
        return None

    entity_token = next(iter(relevance_tokens))
    entity_surface = entity_token
    for raw_token in TOKEN_RE.findall(question):
        if _normalize_token(raw_token) == entity_token:
            entity_surface = raw_token.casefold()
            break

    if SOURCE_LOOKUP_INTENT_RE.search(question):
        return entity_surface, "source_lookup"
    if DEFINITION_INTENT_RE.search(question):
        return f"Что такое {entity_surface}?", "definition"
    return None


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


def _weighted_token_coverage(
    question_tokens: set[str],
    matched_tokens: set[str],
) -> float:
    total_weight = sum(
        LOW_INFORMATION_TOKEN_WEIGHT if token in LOW_INFORMATION_TOKENS else 1.0
        for token in question_tokens
    )
    matched_weight = sum(
        LOW_INFORMATION_TOKEN_WEIGHT if token in LOW_INFORMATION_TOKENS else 1.0
        for token in matched_tokens
    )
    return matched_weight / total_weight if total_weight else 0.0


def score_source_relevance(question: str, chunk: dict) -> SourceRelevanceScore:
    similarity = float(chunk.get("similarity") or 0)
    source_text = str(chunk.get("text") or "")
    question_tokens = extract_relevance_tokens(question)

    # Подписи к рисункам и таблицам часто оказываются близки вопросу по эмбеддингу
    # и названию публикации, но сами по себе не содержат достаточного ответа.
    is_caption = FIGURE_OR_TABLE_CAPTION_RE.match(source_text) is not None
    text_tokens = extract_relevance_tokens(source_text)
    title_tokens = extract_relevance_tokens(
        str(chunk.get("publication_title") or "")
    )
    text_overlap = _matching_question_tokens(question_tokens, text_tokens)
    title_overlap = _matching_question_tokens(question_tokens, title_tokens)
    text_coverage = _weighted_token_coverage(question_tokens, text_overlap)
    title_coverage = _weighted_token_coverage(question_tokens, title_overlap)
    specific_question_tokens = question_tokens - LOW_INFORMATION_TOKENS
    matched_specific_tokens = text_overlap & specific_question_tokens
    is_cross_language = is_cross_language_pair(question, source_text)

    if len(question_tokens) <= 2:
        required_coverage = MIN_SHORT_QUERY_COVERAGE
    elif similarity >= MIN_STRONG_SEMANTIC_SIMILARITY:
        required_coverage = MIN_STRONG_SEMANTIC_COVERAGE
    else:
        required_coverage = MIN_LONG_QUERY_COVERAGE

    generic_high_confidence_match = bool(
        not specific_question_tokens
        and text_overlap
        and similarity >= 0.85
    )
    strong_multitoken_match = bool(
        similarity >= MIN_STRONG_MULTITOKEN_SIMILARITY
        and text_coverage >= MIN_STRONG_MULTITOKEN_COVERAGE
        and len(matched_specific_tokens) >= 3
    )
    direct_geochronology_method_evidence = bool(
        is_geochronology_method_query(question)
        and contains_geochronology_method_evidence(source_text)
        and not is_caption
        and matched_specific_tokens
    )
    is_directly_relevant = bool(
        question_tokens
        and (text_overlap or direct_geochronology_method_evidence)
        and not is_caption
        and (
            text_coverage >= required_coverage
            or generic_high_confidence_match
            or strong_multitoken_match
            or direct_geochronology_method_evidence
        )
        and (
            not specific_question_tokens
            or matched_specific_tokens
            or direct_geochronology_method_evidence
        )
    )
    is_cross_language_relevant = bool(
        is_cross_language
        and not is_caption
        and similarity >= MIN_CROSS_LANGUAGE_SIMILARITY
    )
    is_relevant = is_directly_relevant or is_cross_language_relevant
    combined_score = (
        text_coverage * 0.70
        + similarity * 0.25
        + title_coverage * 0.05
        + (0.40 if direct_geochronology_method_evidence else 0.0)
    )
    return SourceRelevanceScore(
        chunk=chunk,
        similarity=similarity,
        text_coverage=text_coverage,
        title_coverage=title_coverage,
        matched_text_tokens=frozenset(text_overlap),
        question_tokens=frozenset(question_tokens),
        specific_question_tokens=frozenset(specific_question_tokens),
        matched_specific_tokens=frozenset(matched_specific_tokens),
        matched_cross_language_tokens=frozenset(),
        required_text_coverage=required_coverage,
        cross_language_coverage=0.0,
        is_cross_language=is_cross_language,
        is_caption=is_caption,
        generic_high_confidence_match=generic_high_confidence_match,
        strong_multitoken_match=strong_multitoken_match,
        direct_geochronology_method_evidence=(
            direct_geochronology_method_evidence
        ),
        is_directly_relevant=is_directly_relevant,
        is_cross_language_relevant=is_cross_language_relevant,
        score=combined_score,
        is_relevant=is_relevant,
    )


def explain_source_relevance(question: str, chunk: dict) -> dict[str, object]:
    """Return gate inputs and machine-readable rejection reasons.

    This is intentionally diagnostic-only: the decision is produced by the
    same ``score_source_relevance`` call used by the production gate.
    """
    score = score_source_relevance(question, chunk)
    reasons: list[str] = []

    if not score.question_tokens:
        reasons.append("empty_question_tokens")
    if not score.matched_text_tokens:
        reasons.append("no_text_token_overlap")
    if score.is_caption:
        reasons.append("figure_or_table_caption")
    if (
        score.text_coverage < score.required_text_coverage
        and not score.generic_high_confidence_match
    ):
        reasons.append("insufficient_text_coverage")
    if score.specific_question_tokens and not score.matched_specific_tokens:
        reasons.append("no_specific_question_token_match")

    return {
        "directly_relevant": score.is_directly_relevant,
        "cross_language_relevant": score.is_cross_language_relevant,
        "relevance_score": score.score,
        "similarity": score.similarity,
        "text_coverage": score.text_coverage,
        "required_text_coverage": score.required_text_coverage,
        "title_coverage": score.title_coverage,
        "matched_text_tokens": sorted(score.matched_text_tokens),
        "matched_specific_tokens": sorted(score.matched_specific_tokens),
        "matched_cross_language_tokens": sorted(
            score.matched_cross_language_tokens
        ),
        "cross_language_coverage": score.cross_language_coverage,
        "is_cross_language": score.is_cross_language,
        "is_caption": score.is_caption,
        "generic_high_confidence_match": score.generic_high_confidence_match,
        "strong_multitoken_match": score.strong_multitoken_match,
        "direct_geochronology_method_evidence": (
            score.direct_geochronology_method_evidence
        ),
        "rejection_reasons": reasons if not score.is_relevant else [],
    }


def is_relevant_source(question: str, chunk: dict) -> bool:
    return score_source_relevance(question, chunk).is_relevant


def is_cross_language_pair(question: str, source_text: str) -> bool:
    question_cyrillic = len(re.findall(r"[А-Яа-яЁё]", question))
    question_latin = len(re.findall(r"[A-Za-z]", question))
    source_cyrillic = len(re.findall(r"[А-Яа-яЁё]", source_text))
    source_latin = len(re.findall(r"[A-Za-z]", source_text))
    return (
        question_cyrillic > max(3, question_latin * 2)
        and source_latin > max(12, source_cyrillic * 2)
    ) or (
        question_latin > max(3, question_cyrillic * 2)
        and source_cyrillic > max(12, source_latin * 2)
    )


def filter_relevant_sources(
    question: str,
    chunks: list[dict],
    limit: int,
) -> list[dict]:
    scored_chunks = [score_source_relevance(question, chunk) for chunk in chunks]
    relevant_scores = [score for score in scored_chunks if score.is_relevant]

    if not relevant_scores:
        semantic_candidates = sorted(
            (
                score
                for score in scored_chunks
                if not FIGURE_OR_TABLE_CAPTION_RE.match(
                    str(score.chunk.get("text") or "")
                )
                and is_cross_language_pair(
                    question,
                    str(score.chunk.get("text") or ""),
                )
            ),
            key=lambda item: -item.similarity,
        )
        if semantic_candidates:
            best_semantic = semantic_candidates[0]
            next_similarity = (
                semantic_candidates[1].similarity
                if len(semantic_candidates) > 1
                else 0.0
            )
            if (
                best_semantic.similarity >= MIN_CROSS_LANGUAGE_SIMILARITY
                and best_semantic.similarity - next_similarity
                >= MIN_CROSS_LANGUAGE_MARGIN
            ):
                return [best_semantic.chunk]

        return []

    relevant_scores.sort(
        key=lambda item: (-item.score, -item.similarity)
    )
    return [score.chunk for score in relevant_scores[:limit]]


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
    effective_limit = min(limit, MAX_ANSWER_SOURCES)
    return diversify_chunks_by_publication(relevant_chunks, effective_limit)
