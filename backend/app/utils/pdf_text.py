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
