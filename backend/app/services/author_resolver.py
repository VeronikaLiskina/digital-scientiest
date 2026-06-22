from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.author import Author
from app.utils.normalization import (
    format_author_display_name,
    normalize_author_identity_key,
    normalize_author_name,
)


@dataclass(frozen=True)
class AuthorMatchResult:
    extracted_name: str
    canonical_name: str
    author: Author | None

    @property
    def is_existing(self) -> bool:
        return self.author is not None


def _clean_author_input(value: str) -> str:
    return " ".join(value.strip().split())


def _canonical_author_name(value: str) -> str | None:
    """
    Приводит автора к единому формату для сравнения и сохранения.

    Поддерживаемые варианты:
    - Иванов А.В.
    - Иванов А. В.
    - А. В. Иванов
    - Иванов Алексей Викторович
    - Ivanov A. V.
    - A. V. Ivanov
    - Alexei V. Ivanov

    Важно:
    - полные имена не угадываем;
    - если невозможно уверенно получить Фамилия И.О., возвращаем None.
    """

    cleaned = _clean_author_input(value)

    if not cleaned:
        return None

    canonical = format_author_display_name(cleaned)

    if canonical:
        return canonical

    return None


def _author_exact_key(value: str) -> str | None:
    canonical = _canonical_author_name(value)

    if canonical is None:
        return None

    return normalize_author_name(canonical)


def _author_identity_key(value: str) -> str | None:
    canonical = _canonical_author_name(value)

    if canonical is None:
        return None

    return normalize_author_identity_key(canonical)


def _same_author(left_name: str, right_name: str) -> bool:
    """
    Сравнивает двух авторов как одного человека.

    Сначала сравниваем точный normalized_name.
    Потом — мягкий identity_key.
    """

    left_exact = _author_exact_key(left_name)
    right_exact = _author_exact_key(right_name)

    if left_exact and right_exact and left_exact == right_exact:
        return True

    left_identity = _author_identity_key(left_name)
    right_identity = _author_identity_key(right_name)

    if left_identity and right_identity and left_identity == right_identity:
        return True

    return False


async def _find_author_by_exact_key(
    db: AsyncSession,
    normalized_name: str,
) -> Author | None:
    result = await db.execute(
        select(Author).where(Author.normalized_name == normalized_name)
    )

    return result.scalar_one_or_none()


async def _find_author_by_identity_scan(
    db: AsyncSession,
    canonical_name: str,
) -> Author | None:
    """
    Fallback-поиск по всем авторам.

    Для MVP нормально.
    Если авторов станет очень много, можно будет вынести identity_key
    в отдельную колонку в БД.
    """

    result = await db.execute(select(Author))
    authors = result.scalars().all()

    for author in authors:
        if _same_author(canonical_name, author.full_name):
            return author

    return None


def _normalize_existing_author_if_needed(author: Author) -> None:
    """
    Аккуратно приводит старую запись автора в БД к формату Иванов А.В.

    Например:
    Иванов Алексей Викторович -> Иванов А.В.
    Иванов А. В. -> Иванов А.В.
    """

    canonical_name = _canonical_author_name(author.full_name)

    if canonical_name is None:
        return

    if author.full_name != canonical_name:
        author.full_name = canonical_name

    author.normalized_name = normalize_author_name(canonical_name)


async def find_author_by_identity(
    db: AsyncSession,
    full_name: str,
    *,
    normalize_existing: bool = False,
) -> Author | None:
    """
    Ищет автора в БД по разным вариантам записи имени.

    Примеры, которые должны считаться одним автором:
    - Иванов А.В.
    - Иванов А. В.
    - А. В. Иванов
    - Иванов Алексей Викторович
    - Ivanov A. V.
    - A. V. Ivanov
    - Alexei V. Ivanov

    Если normalize_existing=True, найденный автор в БД будет приведён
    к формату Иванов А.В.
    """

    canonical_name = _canonical_author_name(full_name)

    if canonical_name is None:
        return None

    normalized_name = normalize_author_name(canonical_name)

    exact_author = await _find_author_by_exact_key(
        db=db,
        normalized_name=normalized_name,
    )

    if exact_author is not None:
        if normalize_existing:
            _normalize_existing_author_if_needed(exact_author)

        return exact_author

    identity_author = await _find_author_by_identity_scan(
        db=db,
        canonical_name=canonical_name,
    )

    if identity_author is not None:
        if normalize_existing:
            _normalize_existing_author_if_needed(identity_author)

        return identity_author

    return None


async def resolve_author_match(
    db: AsyncSession,
    full_name: str,
) -> AuthorMatchResult | None:
    """
    Используется для предпросмотра PDF.

    Ничего не создаёт и не изменяет в БД.
    Только говорит:
    - автор уже есть;
    - или это новый автор.
    """

    canonical_name = _canonical_author_name(full_name)

    if canonical_name is None:
        return None

    existing_author = await find_author_by_identity(
        db=db,
        full_name=canonical_name,
        normalize_existing=False,
    )

    return AuthorMatchResult(
        extracted_name=full_name,
        canonical_name=canonical_name,
        author=existing_author,
    )


async def resolve_author_matches(
    db: AsyncSession,
    author_names: list[str],
) -> list[AuthorMatchResult]:
    """
    Массовая проверка авторов из PDF.

    Нужна для /source-files/extract-metadata:
    - найденных авторов можно сразу отметить в интерфейсе;
    - новых авторов можно показать в textarea.
    """

    results: list[AuthorMatchResult] = []
    seen: set[str] = set()

    for raw_name in author_names:
        match_result = await resolve_author_match(
            db=db,
            full_name=raw_name,
        )

        if match_result is None:
            continue

        key = normalize_author_name(match_result.canonical_name)

        if key in seen:
            continue

        seen.add(key)
        results.append(match_result)

    return results


async def get_or_create_author(
    db: AsyncSession,
    full_name: str,
    organization: str | None = None,
) -> Author:
    """
    Используется при финальном сохранении публикации.

    На этапе выбора PDF авторы НЕ создаются.
    Здесь:
    - сначала ищем существующего автора;
    - если нашли — возвращаем его;
    - если не нашли — создаём нового.
    """

    canonical_name = _canonical_author_name(full_name)

    if canonical_name is None:
        # Если пользователь вручную ввёл нестандартное имя,
        # не теряем его, но сохраняем очищенным.
        canonical_name = _clean_author_input(full_name)

    existing_author = await find_author_by_identity(
        db=db,
        full_name=canonical_name,
        normalize_existing=True,
    )

    if existing_author is not None:
        return existing_author

    author = Author(
        full_name=canonical_name,
        normalized_name=normalize_author_name(canonical_name),
        organization=organization.strip() if organization else None,
    )

    db.add(author)
    await db.flush()

    return author