import re


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


def _is_latin(value: str) -> bool:
    return bool(re.search(r"[A-Za-z]", value))


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

    # Неизвестную латинскую фамилию не русифицируем.
    # Иначе получится опасный микс типа Smith Д.А.
    return None


def _raw_initial(value: str | None) -> str:
    if not value:
        return ""

    value = value.strip(" .")

    if not value:
        return ""

    return value[:1]


def _format_initial(value: str | None) -> str:
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

    Не угадывает:
    - Alexei Ivanov
    - John Smith
    """

    value = _clean_author_value(value)

    if not value:
        return None

    # А. В. Иванов / A. V. Ivanov
    match = re.fullmatch(
        r"([A-ZА-ЯЁ])\.\s*([A-ZА-ЯЁ])\.\s*([A-ZА-ЯЁ][A-Za-zА-Яа-яЁё'’\-]+)",
        value,
    )

    if match:
        first_initial, second_initial, last_name = match.groups()

        return _compose_author_name(
            last_name=last_name,
            first_initial_source=first_initial,
            second_initial_source=second_initial,
        )

    # Иванов А. В. / Иванов А.В. / Ivanov A. V.
    match = re.fullmatch(
        r"([A-ZА-ЯЁ][A-Za-zА-Яа-яЁё'’\-]+)\s+([A-ZА-ЯЁ])\.\s*([A-ZА-ЯЁ])\.?",
        value,
    )

    if match:
        last_name, first_initial, second_initial = match.groups()

        return _compose_author_name(
            last_name=last_name,
            first_initial_source=first_initial,
            second_initial_source=second_initial,
        )

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

    # Alexei Ivanov — второго инициала нет.
    # Не угадываем отчество.
    if re.fullmatch(
        r"[A-Z][a-zA-Z'’\-]+\s+[A-Z][a-zA-Z'’\-]+",
        value,
    ):
        return None

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


def normalize_keyword(value: str) -> str:
    return _normalize_common(value)


def normalize_topic(value: str) -> str:
    return _normalize_common(value)
