from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.keyword import Keyword
from app.utils.normalization import normalize_keyword


async def get_or_create_keyword(
    db: AsyncSession,
    name: str,
) -> Keyword:
    normalized_name = normalize_keyword(name)

    result = await db.execute(
        select(Keyword).where(Keyword.normalized_name == normalized_name)
    )
    keyword = result.scalar_one_or_none()

    if keyword is not None:
        return keyword

    keyword = Keyword(
        name=name.strip(),
        normalized_name=normalized_name,
    )
    db.add(keyword)
    await db.flush()
    return keyword
