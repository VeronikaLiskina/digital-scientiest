import re
import unicodedata


_SPACES_RE = re.compile(r"\s+")


_LATIN_INITIAL_TO_RU = {
    "A": "А",
    "B": "Б",
    "C": "К",
    "D": "Д",
    "E": "Е",
    "F": "Ф",
    "G": "Г",
    "H": "Х",
    "I": "И",
    "J": "Д",
    "K": "К",
    "L": "Л",
    "M": "М",
    "N": "Н",
    "O": "О",
    "P": "П",
    "R": "Р",
    "S": "С",
    "T": "Т",
    "U": "У",
    "V": "В",
    "Y": "Ю",
    "Z": "З",
}


LATIN_LAST_NAME_MAP = {
    "ivanov": "Иванов",
    "demonterova": "Демонтерова",
    "dementerova": "Демонтерова",
    "maltsev": "Мальцев",
    "zhilicheva": "Жиличева",
    "reznitskii": "Резницкий",
    "reznitsky": "Резницкий",
    "arzhannikov": "Аржанников",
    "arzhannikova": "Аржанникова",
    "blinov": "Блинов",
    "khubanov": "Хубанов",
    "kiselev": "Киселев",
    "danilov": "Данилов",
    "soloveva": "Соловьева",
    "kalashnikova": "Калашникова",
    "kostrovitsky": "Костровицкий",
    "matsuk": "Мацюк",
    "suvorova": "Суворова",
    "perepelov": "Перепелов",
    "puzankov": "Пузанков",
    "antipin": "Антипин",
    "yazev": "Язев",
    "kuzmin": "Кузьмин",
    "efremov": "Ефремов",
    "mitichkin": "Митичкин",
    "mikheeva": "Михеева",
    "filosofova": "Философова",
    "smirnova": "Смирнова",
    "chuvashova": "Чувашова",
    "yasnygina": "Ясныгина",
    "chetvertakov": "Четвертаков",
    "chikisheva": "Чикишева",
    "danilova": "Данилова",
    "savelyeva": "Савельева",
    "shumilova": "Шумилова",
    "bazarova": "Базарова",
    "levitsky": "Левицкий",
    "levitskii": "Левицкий",
    "lomyga": "Ломыга",
    "vanin": "Ванин",
    "gorovoy": "Горовой",
    "budyak": "Будяк",
    "bortnikov": "Бортников",
    "malyshev": "Малышев",
    "pasenko": "Пасенко",
    "khudoley": "Худолей",
    "priyatkina": "Прияткина",
    "pazukhina": "Пазухина",
    "marfin": "Марфин",
    "dufrane": "Дюфрейн",
    "sharygin": "Шарыгин",
    "gladkochub": "Гладкочуб",
    "fiorentini": "Фиорентини",
    "paton": "Патон",
}


def _normalize_common(value: str) -> str:
    value = value.strip().lower().replace("ё", "е")
    return _SPACES_RE.sub(" ", value)


def _clean_author_value(value: str) -> str:
    value = value.replace("\u00a0", " ")
    value = " ".join(value.strip().split())

    # А . В . Иванов -> А. В. Иванов
    value = re.sub(r"([A-ZА-ЯЁ])\s+\.", r"\1.", value)

    # А.В. Иванов -> А. В. Иванов
    value = re.sub(
        r"\b([A-ZА-ЯЁ])\.([A-ZА-ЯЁ])\.",
        r"\1. \2.",
        value,
    )

    value = re.sub(r"\s+", " ", value)
    return value.strip(" .;,:—-–")


def _is_cyrillic(value: str) -> bool:
    return bool(re.search(r"[А-Яа-яЁё]", value))


def _format_word(value: str) -> str:
    value = value.strip(" .")

    if not value:
        return ""

    parts = value.split("-")

    formatted_parts = [
        part[:1].upper() + part[1:].lower()
        if part
        else part
        for part in parts
    ]

    return "-".join(formatted_parts)


def _format_last_name(value: str) -> str | None:
    value = value.strip(" .")

    if not value:
        return None

    if _is_cyrillic(value):
        return _format_word(value)

    normalized = value.lower().replace("ё", "е")

    if normalized in LATIN_LAST_NAME_MAP:
        return LATIN_LAST_NAME_MAP[normalized]

    return _format_word(value) if value.isupper() else value[:1].upper() + value[1:]


def _raw_initial(value: str | None) -> str:
    if not value:
        return ""

    value = value.strip(" .")

    if not value:
        return ""

    return value[:1]


def _format_initial(value: str | None) -> str:
    digraphs = {"yu": "Ю", "ya": "Я", "yo": "Ё", "zh": "Ж", "kh": "Х", "ch": "Ч", "sh": "Ш"}
    if value and value.strip(" .").casefold() in digraphs:
        return digraphs[value.strip(" .").casefold()] + "."
    initial = _raw_initial(value)

    if not initial:
        return ""

    initial = initial.upper()
    initial = _LATIN_INITIAL_TO_RU.get(initial, initial)

    return f"{initial}."


def _compose_author_name(
    last_name: str,
    first_initial_source: str,
    second_initial_source: str,
) -> str | None:
    formatted_last_name = _format_last_name(last_name)
    first_initial = _format_initial(first_initial_source)
    second_initial = _format_initial(second_initial_source)
    if formatted_last_name and not _is_cyrillic(formatted_last_name):
        first_initial = _latin_initial(first_initial_source) + "."
        second_initial = _latin_initial(second_initial_source) + "."

    if not formatted_last_name or not first_initial or not second_initial:
        return None

    return f"{formatted_last_name} {first_initial}{second_initial}"


def format_author_display_name(value: str) -> str | None:
    """
    Приводит автора к виду: Иванов А.В.

    Поддерживает:
    - Иванов А.В.
    - Иванов А. В.
    - А. В. Иванов
    - Иванов Алексей Викторович
    - Иванов Алексей В.
    - Ivanov A. V.
    - A. V. Ivanov
    - Alexei V. Ivanov

    Сохраняет английские имена без отчества (Alexei Ivanov, John Smith),
    не добавляя отсутствующие инициалы.
    """

    value = _clean_author_value(value)

    if not value:
        return None

    # А. В. Иванов / A. V. Ivanov
    initial_token = r"(?:[A-ZА-ЯЁ]|Yu|Ya|Yo|Zh|Kh|Ch|Sh)"
    surname_token = r"[A-ZА-ЯЁ][A-Za-zА-Яа-яЁё'’\-]+"
    extended = re.fullmatch(rf"({initial_token})\.\s*({initial_token})\.\s*({surname_token})", value)
    if extended:
        first, second, last = extended.groups()
        return _compose_author_name(last, first, second)
    extended = re.fullmatch(rf"({surname_token})\s+({initial_token})\.\s*({initial_token})\.?", value)
    if extended:
        last, first, second = extended.groups()
        return _compose_author_name(last, first, second)
    single = re.fullmatch(rf"({initial_token})\.\s*({surname_token})", value)
    if single:
        first, last = single.groups()
        formatted = _format_last_name(last)
        initial = _format_initial(first) if _is_cyrillic(formatted) else _latin_initial(first) + "."
        return f"{formatted} {initial}"
    single = re.fullmatch(rf"({surname_token})\s+({initial_token})\.?", value)
    if single:
        last, first = single.groups()
        formatted = _format_last_name(last)
        initial = _format_initial(first) if _is_cyrillic(formatted) else _latin_initial(first) + "."
        return f"{formatted} {initial}"
    # Иванов Алексей Викторович
    match = re.fullmatch(
        r"([А-ЯЁ][а-яё\-]+)\s+([А-ЯЁ][а-яё\-]+)\s+([А-ЯЁ][а-яё\-]+)",
        value,
    )

    if match:
        last_name, first_name, patronymic = match.groups()

        return _compose_author_name(
            last_name=last_name,
            first_initial_source=first_name,
            second_initial_source=patronymic,
        )

    # Иванов Алексей В.
    match = re.fullmatch(
        r"([А-ЯЁ][а-яё\-]+)\s+([А-ЯЁ][а-яё\-]+)\s+([А-ЯЁ])\.?",
        value,
    )

    if match:
        last_name, first_name, patronymic_initial = match.groups()

        return _compose_author_name(
            last_name=last_name,
            first_initial_source=first_name,
            second_initial_source=patronymic_initial,
        )

    # Ivanov Alexei V.
    match = re.fullmatch(
        r"([A-Z][a-zA-Z'’\-]+)\s+([A-Z][a-zA-Z'’\-]+)\s+([A-Z])\.?",
        value,
    )

    if match:
        last_name, first_name, second_initial = match.groups()

        return _compose_author_name(
            last_name=last_name,
            first_initial_source=first_name,
            second_initial_source=second_initial,
        )

    # Alexei V. Ivanov
    match = re.fullmatch(
        r"([A-Z][a-zA-Z'’\-]+)\s+([A-Z])\.\s*([A-Z][a-zA-Z'’\-]+)",
        value,
    )

    if match:
        first_name, second_initial, last_name = match.groups()

        return _compose_author_name(
            last_name=last_name,
            first_initial_source=first_name,
            second_initial_source=second_initial,
        )

    # Preserve English full names without inventing a missing patronymic.
    if re.fullmatch(
        r"[A-Z][a-zA-Z'’\-]+\s+[A-Z][a-zA-Z'’\-]+",
        value,
    ):
        return value

    return None


def normalize_author_name(value: str) -> str:
    """
    Точный ключ для поиска дублей.

    Иванов А. В. -> иванова.в.
    Ivanov A. V. -> иванова.в.
    Alexei V. Ivanov -> иванова.в.
    """

    display_name = format_author_display_name(value) or _clean_author_value(value)

    value = _normalize_common(display_name)
    value = re.sub(r"\s+([а-яa-z]\.)", r"\1", value)

    return value


def _prepare_author_identity_value(value: str) -> str:
    display_name = format_author_display_name(value)

    if display_name:
        value = display_name

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
    Мягкий ключ личности автора.

    Все варианты должны давать один результат:
    - Иванов А.В. -> иванов а в
    - Иванов А. В. -> иванов а в
    - А. В. Иванов -> иванов а в
    - Ivanov A. V. -> иванов а в
    - A. V. Ivanov -> иванов а в
    - Alexei V. Ivanov -> иванов а в
    """

    value = _prepare_author_identity_value(value)

    if not value:
        return None

    # А. В. Иванов
    match = re.fullmatch(
        r"([а-яa-z])\.\s*([а-яa-z])\.\s+([а-яa-z'’\-]+)",
        value,
    )

    if match:
        first_initial, second_initial, last_name = match.groups()
        return f"{last_name} {_initial(first_initial)} {_initial(second_initial)}"

    # Иванов А. В.
    match = re.fullmatch(
        r"([а-яa-z'’\-]+)\s+([а-яa-z])\.\s*([а-яa-z])\.?",
        value,
    )

    if match:
        last_name, first_initial, second_initial = match.groups()
        return f"{last_name} {_initial(first_initial)} {_initial(second_initial)}"

    # Иванов Алексей В.
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

    return None


_RU_TO_LATIN = dict(zip(
    "абвгдеёжзийклмнопрстуфхцчшщъыьэюя",
    ("a", "b", "v", "g", "d", "e", "e", "zh", "z", "i", "y", "k", "l", "m", "n", "o", "p", "r", "s", "t", "u", "f", "kh", "ts", "ch", "sh", "shch", "", "y", "", "e", "yu", "ya"),
))


def _latin_initial(value: str) -> str:
    value = value.strip(" .").casefold()
    if not value:
        return ""
    if value in {"yu", "ya", "yo", "zh", "kh", "ch", "sh"}:
        return value.title()
    return _RU_TO_LATIN.get(value[0], value[0]).upper()


def _transliterated_token(value: str) -> str:
    value = "".join(_RU_TO_LATIN.get(char, char) for char in value.casefold())
    value = "".join(char for char in unicodedata.normalize("NFKD", value) if not unicodedata.combining(char))
    value = re.sub(r"(?:skiy|skii|skij|sky)$", "sky", value)
    return re.sub(r"[^a-z-]", "", value)


def author_identity_signature(value: str) -> tuple[str, tuple[str, ...]] | None:
    value = _clean_author_value(format_author_display_name(value) or value)
    surname = r"[A-ZА-ЯЁ][A-Za-zА-Яа-яЁё'’\-]+"
    initials = r"(?:[A-ZА-ЯЁ]|Yu|Ya|Yo|Zh|Kh|Ch|Sh)"
    match = re.fullmatch(rf"({surname})\s+({initials})\.\s*({initials})\.?", value)
    if match:
        last, first, second = match.groups()
        return _transliterated_token(last), (_transliterated_token(_latin_initial(first)), _transliterated_token(_latin_initial(second)))
    match = re.fullmatch(rf"({surname})\s+({initials})\.?", value)
    if match:
        last, first = match.groups()
        return _transliterated_token(last), (_transliterated_token(_latin_initial(first)),)
    match = re.fullmatch(rf"({surname})\s+({surname})", value)
    if match and not _is_cyrillic(value):
        first, last = match.groups()
        return _transliterated_token(last), (_transliterated_token(_latin_initial(first)),)
    return None


def author_names_match(left: str, right: str) -> bool:
    # Two explicitly written English first names are stronger evidence than
    # their shared initial (John Smith must not become James Smith).
    full = r"([A-Z][a-z]{1,})\s+([A-Z][a-z'’\-]{1,})"
    left_full, right_full = re.fullmatch(full, left.strip()), re.fullmatch(full, right.strip())
    if left_full and right_full and left_full[1].casefold() != right_full[1].casefold():
        return False
    first = author_identity_signature(left)
    second = author_identity_signature(right)
    if first is None or second is None or first[0] != second[0]:
        return False
    # Callers require an unambiguous row when the English name has no middle initial.
    return all(a == b for a, b in zip(first[1], second[1]))


def normalize_keyword(value: str) -> str:
    return _normalize_common(value)


def normalize_topic(value: str) -> str:
    return _normalize_common(value)
