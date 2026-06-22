import re


_SPACES_RE = re.compile(r"\s+")

_LATIN_INITIAL_TO_RU = {
    "A": "А", "B": "Б", "C": "К", "D": "Д", "E": "Е", "F": "Ф",
    "G": "Г", "H": "Х", "I": "И", "J": "Д", "K": "К", "L": "Л",
    "M": "М", "N": "Н", "O": "О", "P": "П", "R": "Р", "S": "С",
    "T": "Т", "U": "У", "V": "В", "Y": "Ю", "Z": "З",
}


def _normalize_common(value: str) -> str:
    value = value.strip().lower().replace("ё", "е")
    return _SPACES_RE.sub(" ", value)


def normalize_author_name(value: str) -> str:
    """
    Приводит ФИО автора к единому виду для точного поиска дублей.

    Примеры:
    - " Иванов И. И. " -> "иванов и.и."
    - "Иванов  И.И." -> "иванов и.и."
    - "Иванов Алексей Викторович" -> "иванов а.в."
    """

    display_name = format_author_display_name(value) or value
    value = _normalize_common(display_name)
    value = re.sub(r"\s+([а-яa-z]\.)", r"\1", value)
    return value


def _prepare_author_identity_value(value: str) -> str:
    value = _normalize_common(value)
    value = re.sub(r"[,:;()\[\]{}]", " ", value)
    value = re.sub(r"([а-яa-z])\.\s*([а-яa-z])\.", r"\1. \2.", value)
    value = re.sub(r"\s+", " ", value)
    return value.strip(" .")


def _initial(value: str | None) -> str:
    if not value:
        return ""

    value = value.strip(" .")
    return value[:1] if value else ""


def normalize_author_identity_key(value: str) -> str | None:
    """
    Более мягкий ключ для поиска одного и того же автора.

    Он нужен для случаев, когда в БД уже есть "Иванов А.В.",
    а из PDF пришло "Иванов Алексей В." или "Иванов Алексей Викторович".

    Примеры:
    - Иванов А.В. -> иванов а в
    - Иванов А. В. -> иванов а в
    - Иванов Алексей В. -> иванов а в
    - Иванов Алексей Викторович -> иванов а в
    - А. В. Иванов -> иванов а в

    Если не получается уверенно понять структуру ФИО, возвращается None.
    """

    value = _prepare_author_identity_value(value)

    if not value:
        return None

    # А. В. Иванов / A. V. Ivanov
    match = re.fullmatch(
        r"([а-яa-z])\.\s*([а-яa-z])\.\s+([а-яa-z'’\-]+)",
        value,
    )
    if match:
        first_initial, second_initial, last_name = match.groups()
        return f"{last_name} {_initial(first_initial)} {_initial(second_initial)}"

    # Иванов А. В. / Ivanov A. V.
    match = re.fullmatch(
        r"([а-яa-z'’\-]+)\s+([а-яa-z])\.\s*([а-яa-z])\.?",
        value,
    )
    if match:
        last_name, first_initial, second_initial = match.groups()
        return f"{last_name} {_initial(first_initial)} {_initial(second_initial)}"

    # Иванов Алексей В. / Ivanov Alexei V.
    match = re.fullmatch(
        r"([а-яa-z'’\-]+)\s+([а-яa-z'’\-]+)\s+([а-яa-z])\.?",
        value,
    )
    if match:
        last_name, first_name, second_initial = match.groups()
        return f"{last_name} {_initial(first_name)} {_initial(second_initial)}"

    # Иванов Алексей Викторович
    match = re.fullmatch(
        r"([а-яa-z'’\-]+)\s+([а-яa-z'’\-]+)\s+([а-яa-z'’\-]+)",
        value,
    )
    if match:
        last_name, first_name, patronymic = match.groups()
        return f"{last_name} {_initial(first_name)} {_initial(patronymic)}"

    # Alexei V. Ivanov
    match = re.fullmatch(
        r"([a-z'’\-]+)\s+([a-z])\.\s+([a-z'’\-]+)",
        value,
    )
    if match:
        first_name, second_initial, last_name = match.groups()
        return f"{last_name} {_initial(first_name)} {_initial(second_initial)}"

    # Alexei Ivanov -> ivanov a
    match = re.fullmatch(
        r"([a-z'’\-]+)\s+([a-z'’\-]+)",
        value,
    )
    if match:
        first_name, last_name = match.groups()
        return f"{last_name} {_initial(first_name)}"

    return None


def _format_word(value: str) -> str:
    value = value.strip(" .")
    if not value:
        return ""

    parts = value.split("-")
    formatted_parts = [part[:1].upper() + part[1:].lower() if part else part for part in parts]
    return "-".join(formatted_parts)


def _format_initial(value: str | None) -> str:
    initial = _initial(value)

    if not initial:
        return ""

    initial = initial.upper()
    initial = _LATIN_INITIAL_TO_RU.get(initial, initial)
    return f"{initial}."


def format_author_display_name(value: str) -> str | None:
    """
    Приводит имя автора к отображаемому формату: Фамилия И.О.

    Примеры:
    - Иванов Алексей Викторович -> Иванов А.В.
    - Иванов Алексей В. -> Иванов А.В.
    - Иванов А. В. -> Иванов А.В.
    - Иванов А.В -> Иванов А.В.
    - А. В. Иванов -> Иванов А.В.

    Если структуру имени невозможно распознать уверенно, возвращает исходную
    строку в очищенном виде, а не выдумывает ФИО.
    """

    original = value.strip()
    prepared = _prepare_author_identity_value(value)

    if not prepared:
        return None

    # А. В. Иванов / A. V. Ivanov
    match = re.fullmatch(
        r"([а-яa-z])\.\s*([а-яa-z])\.\s+([а-яa-z'’\-]+)",
        prepared,
    )
    if match:
        first_initial, second_initial, last_name = match.groups()
        return f"{_format_word(last_name)} {_format_initial(first_initial)}{_format_initial(second_initial)}"

    # Иванов А. В. / Иванов А.В. / Ivanov A. V.
    match = re.fullmatch(
        r"([а-яa-z'’\-]+)\s+([а-яa-z])\.\s*([а-яa-z])\.?",
        prepared,
    )
    if match:
        last_name, first_initial, second_initial = match.groups()
        return f"{_format_word(last_name)} {_format_initial(first_initial)}{_format_initial(second_initial)}"

    # Иванов Алексей В. / Ivanov Alexei V.
    match = re.fullmatch(
        r"([а-яa-z'’\-]+)\s+([а-яa-z'’\-]+)\s+([а-яa-z])\.?",
        prepared,
    )
    if match:
        last_name, first_name, second_initial = match.groups()
        return f"{_format_word(last_name)} {_format_initial(first_name)}{_format_initial(second_initial)}"

    # Иванов Алексей Викторович
    match = re.fullmatch(
        r"([а-яa-z'’\-]+)\s+([а-яa-z'’\-]+)\s+([а-яa-z'’\-]+)",
        prepared,
    )
    if match:
        last_name, first_name, patronymic = match.groups()
        return f"{_format_word(last_name)} {_format_initial(first_name)}{_format_initial(patronymic)}"

    # Alexei V. Ivanov
    match = re.fullmatch(
        r"([a-z'’\-]+)\s+([a-z])\.\s+([a-z'’\-]+)",
        prepared,
    )
    if match:
        first_name, second_initial, last_name = match.groups()
        return f"{_format_word(last_name)} {_format_initial(first_name)}{_format_initial(second_initial)}"

    # Alexei Ivanov -> Ivanov A.
    match = re.fullmatch(
        r"([a-z'’\-]+)\s+([a-z'’\-]+)",
        prepared,
    )
    if match:
        first_name, last_name = match.groups()
        return f"{_format_word(last_name)} {_format_initial(first_name)}"

    return re.sub(r"\s+", " ", original)


def normalize_keyword(value: str) -> str:
    return _normalize_common(value)


def normalize_topic(value: str) -> str:
    return _normalize_common(value)
