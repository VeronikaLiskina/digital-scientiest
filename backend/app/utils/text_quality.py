"""Detect broken PDF font mappings without a dictionary or another model."""
import re
import unicodedata


WORD_RE = re.compile(r"[^\W\d_]+", re.UNICODE)
CID_RE = re.compile(r"\(cid:\s*\d+\)", re.IGNORECASE)
MOJIBAKE_RE = re.compile(r"(?:[РС][\u0080-\u00bfА-Яа-яЁёЂ-џ]){3,}")
REPEATED_CHARACTER_RE = re.compile(r"([^\W_])\1{5,}", re.UNICODE)


def has_text_corruption(text: str, *, strict: bool = True) -> bool:
    """Strict checks protect individual fields; page checks tolerate stray glyphs."""
    text = unicodedata.normalize("NFKC", text)
    visible = [character for character in text if not character.isspace()]
    if not visible:
        return False

    broken_count = sum(
        character in "\ufffd\ufffe\uffff"
        or unicodedata.category(character) in {"Co", "Cs", "Cc"}
        for character in visible
    )
    if broken_count > (0 if strict else max(2, len(visible) * 0.01)):
        return True
    if CID_RE.search(text) or MOJIBAKE_RE.search(text):
        return True
    if len(re.findall(r"[ÃÂÐÑ]", text)) >= 2 or REPEATED_CHARACTER_RE.search(text):
        return True
    letters = sum(character.isalpha() for character in visible)
    supported_letters = len(re.findall(r"[A-Za-zА-Яа-яЁё]", text))
    if letters >= 4 and supported_letters / letters < 0.65:
        return True

    words = WORD_RE.findall(text)
    if not words:
        return False
    mixed_words = sum(
        len(word) >= 4
        and bool(re.search(r"[A-Za-z]", word))
        and bool(re.search(r"[А-Яа-яЁё]", word))
        for word in words
    )
    if mixed_words and (strict or mixed_words / len(words) >= 0.2):
        return True
    # Letter-by-letter extraction is unsuitable for titles, authors and search.
    return len(words) >= 8 and sum(len(word) == 1 for word in words) / len(words) > 0.6


def is_readable_text(text: str, *, strict: bool = False) -> bool:
    text = unicodedata.normalize("NFKC", text)
    visible = [character for character in text if not character.isspace()]
    letters = sum(character.isalpha() for character in visible)
    supported_letters = len(re.findall(r"[A-Za-zА-Яа-яЁё]", text))
    return (
        letters >= 3
        and supported_letters / max(1, letters) >= 0.65
        and letters / max(1, len(visible)) >= 0.45
        and not has_text_corruption(text, strict=strict)
    )
