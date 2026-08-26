from __future__ import annotations

import re
from functools import lru_cache

import pymorphy3


TOKEN_RE = re.compile(r"[A-Za-zА-Яа-яЁё0-9]{2,}")
RUSSIAN_RE = re.compile(r"[а-яё]", re.IGNORECASE)
GEOCHRONOLOGY_METHOD_QUERY_RE = re.compile(
    r"(?:геохронолог\w*|(?:метод\w*\s+)?(?:изотопн\w+\s+)?датирован\w*|"
    r"датирован\w*\s+метод\w*|dating\s+(?:method|technique)s?)",
    re.IGNORECASE,
)
GEOCHRONOLOGY_METHOD_EVIDENCE_RE = re.compile(
    r"(?:40\s*Ar\s*/\s*39\s*Ar|206\s*Pb\s*/\s*238\s*U|"
    r"U\s*[-–—]?\s*Pb|Rb\s*[-–—]?\s*Sr|Sm\s*[-–—]?\s*Nd|"
    r"SHRIMP(?:\s*[-–—]?\s*II)?|"
    r"(?:радио)?изотопн\w*\s+датирован\w*)",
    re.IGNORECASE,
)
GEOCHRONOLOGY_FTS_MARKERS = (
    "радиоизотопн",
    "изотопн",
    "датирован",
    "shrimp",
    "40ar/39ar",
    "206pb/238u",
    "u-pb",
    "u–pb",
)
GEOCHRONOLOGY_ASPECT_FTS_MARKERS: dict[str, tuple[str, ...]] = {
    "рудный": ("ore", "mineralisation", "mineralization"),
    "магматический": ("magmatic", "magmatism"),
}

CYRILLIC_TRANSLITERATION = str.maketrans(
    {
        "а": "a",
        "б": "b",
        "в": "v",
        "г": "g",
        "д": "d",
        "е": "e",
        "ё": "e",
        "ж": "zh",
        "з": "z",
        "и": "i",
        "й": "y",
        "к": "k",
        "л": "l",
        "м": "m",
        "н": "n",
        "о": "o",
        "п": "p",
        "р": "r",
        "с": "s",
        "т": "t",
        "у": "u",
        "ф": "f",
        "х": "kh",
        "ц": "ts",
        "ч": "ch",
        "ш": "sh",
        "щ": "shch",
        "ъ": "",
        "ы": "y",
        "ь": "",
        "э": "e",
        "ю": "yu",
        "я": "ya",
    }
)
RUSSIAN_ADJECTIVE_SUFFIXES = (
    "ический",
    "ическая",
    "ическое",
    "ский",
    "ская",
    "ское",
)


@lru_cache(maxsize=1)
def _get_morphology() -> pymorphy3.MorphAnalyzer:
    return pymorphy3.MorphAnalyzer()


def _deduplicate(values: list[str]) -> list[str]:
    return list(dict.fromkeys(value.casefold() for value in values if value.strip()))


def is_geochronology_method_query(query_text: str) -> bool:
    return GEOCHRONOLOGY_METHOD_QUERY_RE.search(query_text) is not None


def contains_geochronology_method_evidence(source_text: str) -> bool:
    return GEOCHRONOLOGY_METHOD_EVIDENCE_RE.search(source_text) is not None


def extract_geochronology_aspect_terms(query_text: str) -> list[str]:
    """Return requested process aspects for a dating-method question."""
    if not is_geochronology_method_query(query_text):
        return []

    aspects: list[str] = []
    morph = _get_morphology()
    for raw_token in TOKEN_RE.findall(query_text):
        token = raw_token.casefold().replace("ё", "е")
        if not RUSSIAN_RE.search(token):
            continue
        normalized = morph.parse(token)[0].normal_form.replace("ё", "е")
        aspects.extend(GEOCHRONOLOGY_ASPECT_FTS_MARKERS.get(normalized, ()))
    return _deduplicate(aspects)


def build_geochronology_reranker_query(query_text: str) -> str | None:
    """Normalize broad dating-method wording for passage-level reranking."""
    if not is_geochronology_method_query(query_text):
        return None
    # This is an intent paraphrase, not an answer: it deliberately contains no
    # isotope system or instrument name that could bias the retrieved facts.
    return "Какими методами выполнялось радиоизотопное датирование?"


def _transliterated_variants(normalized_token: str) -> list[str]:
    variants = [normalized_token.translate(CYRILLIC_TRANSLITERATION)]
    for suffix in RUSSIAN_ADJECTIVE_SUFFIXES:
        if normalized_token.endswith(suffix):
            root = normalized_token[: -len(suffix)]
            if len(root) >= 4:
                variants.append(root.translate(CYRILLIC_TRANSLITERATION))
            break
    return variants


def expand_scientific_query_terms(
    query_text: str,
    *,
    original_terms: list[str],
    stopwords: set[str],
) -> list[str]:
    """Add lemmas, English equivalents, and transliterated entity roots."""
    expanded = list(original_terms)
    morph = _get_morphology()

    for raw_token in TOKEN_RE.findall(query_text):
        token = raw_token.casefold().replace("ё", "е")
        if not RUSSIAN_RE.search(token):
            continue
        normalized = morph.parse(token)[0].normal_form.replace("ё", "е")
        if normalized in stopwords:
            continue
        # Preserve short capitalized place names before morphology-based
        # length filtering (for example, pymorphy reduces "Уда" to "уд").
        if raw_token[:1].isupper() and len(token) >= 3:
            expanded.append(token.translate(CYRILLIC_TRANSLITERATION))
        if len(normalized) < 3:
            continue
        expanded.append(normalized)
        if len(normalized) >= 5:
            expanded.extend(_transliterated_variants(normalized))
        # Proper names can be misparsed as common nouns (for example Мурун).
        # Keep a direct transliteration of the surface form as a safe variant.
        if len(token) >= 5 and token != normalized:
            expanded.append(token.translate(CYRILLIC_TRANSLITERATION))

    return _deduplicate(expanded)


def extract_scientific_entity_terms(
    query_text: str,
    *,
    stopwords: set[str],
) -> list[str]:
    """Return high-signal transliterated names for a small FTS rank bonus."""
    boosted: list[str] = []
    morph = _get_morphology()

    for raw_token in TOKEN_RE.findall(query_text):
        token = raw_token.casefold().replace("ё", "е")
        if not RUSSIAN_RE.search(token):
            continue
        normalized = morph.parse(token)[0].normal_form.replace("ё", "е")
        if normalized in stopwords:
            continue

        if raw_token[:1].isupper() and len(token) >= 3:
            boosted.append(token.translate(CYRILLIC_TRANSLITERATION))
    if is_geochronology_method_query(query_text):
        boosted.extend(GEOCHRONOLOGY_FTS_MARKERS)
        # Composite questions often ask about separate magmatic and ore
        # processes. Preserve both English-language evidence branches in the
        # lexical candidate pool instead of letting generic dating hits crowd
        # one of the requested aspects out.
        boosted.extend(extract_geochronology_aspect_terms(query_text))

    return _deduplicate(boosted)

