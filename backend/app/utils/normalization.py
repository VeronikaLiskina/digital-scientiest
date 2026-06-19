import re


_SPACES_RE = re.compile(r"\s+")


def _normalize_common(value: str) -> str:
    value = value.strip().lower().replace("ё", "е")
    return _SPACES_RE.sub(" ", value)


def normalize_author_name(value: str) -> str:
    """
    Приводит ФИО автора к единому виду для поиска дублей.

    Примеры:
    - " Иванов И. И. " -> "иванов и.и."
    - "Иванов  И.И." -> "иванов и.и."
    """

    value = _normalize_common(value)
    value = re.sub(r"\s+([а-яa-z]\.)", r"\1", value)
    return value


def normalize_keyword(value: str) -> str:
    return _normalize_common(value)


def normalize_topic(value: str) -> str:
    return _normalize_common(value)
