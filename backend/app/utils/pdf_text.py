import re


def repair_cyrillic_mojibake(text: str) -> str:
    """
    Чинит старые русские PDF, где pypdf возвращает:
    èÖêÇõÖ ÑÄççõÖ
    вместо:
    ПЕРВЫЕ ДАННЫЕ
    """

    if not text:
        return ""

    try:
        repaired = text.encode("mac_roman", errors="ignore").decode(
            "mac_cyrillic",
            errors="ignore",
        )
    except UnicodeError:
        return text

    original_cyrillic_count = len(re.findall(r"[А-Яа-яЁё]", text))
    repaired_cyrillic_count = len(re.findall(r"[А-Яа-яЁё]", repaired))

    if repaired_cyrillic_count >= 30 and repaired_cyrillic_count > original_cyrillic_count * 3:
        return repaired

    return text


def normalize_pdf_text(text: str) -> str:
    if not text:
        return ""

    text = text.replace("\u00a0", " ")
    text = text.replace("\u00ad", "")
    text = text.replace("\ufffe", "t")
    text = text.replace("￾", "t")

    text = repair_cyrillic_mojibake(text)

    text = re.sub(r"([A-ZА-ЯЁ])\s+\.", r"\1.", text)
    text = re.sub(r"(\w)-\s+(\w)", r"\1\2", text)
    text = re.sub(r"[ \t]+", " ", text)

    return text.strip()


def detect_text_language(text: str, fallback_text: str | None = None) -> str | None:
    combined_text = f"{text}\n{fallback_text or ''}"

    cyrillic_count = len(re.findall(r"[А-Яа-яЁё]", combined_text))
    latin_count = len(re.findall(r"[A-Za-z]", combined_text))

    if cyrillic_count == 0 and latin_count == 0:
        return None

    return "ru" if cyrillic_count > latin_count else "en"


def is_text_extraction_bad(text: str) -> bool:
    """
    Грубая проверка: pypdf что-то извлек, но это похоже на мусор.
    """

    if not text.strip():
        return True

    bad_symbols_count = len(re.findall(r"[�￾]", text))
    letters_count = len(re.findall(r"[A-Za-zА-Яа-яЁё]", text))

    if letters_count < 50:
        return True

    if bad_symbols_count > 20:
        return True
  