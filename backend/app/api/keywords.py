from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.database import get_db
from app.models.keyword import Keyword
from app.schemas.keyword import KeywordCreate, KeywordRead, KeywordUpdate
from app.services.keyword_resolver import get_or_create_keyword
from app.utils.normalization import normalize_keyword


router = APIRouter(prefix="/keywords", tags=["Keywords"])


@router.post("", response_model=KeywordRead, status_code=status.HTTP_201_CREATED)
async def create_keyword(
    data: KeywordCreate,
    db: AsyncSession = Depends(get_db),
):
    keyword = await get_or_create_keyword(db=db, name=data.name)
    await db.commit()
    await db.refresh(keyword)
    return keyword


@router.get("", response_model=list[KeywordRead])
async def get_keywords(
    search: str | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
):
    query = select(Keyword).order_by(Keyword.name)

    if search:
        query = query.where(Keyword.name.ilike(f"%{search}%"))

    result = await db.execute(query)
    return result.scalars().all()


@router.get("/{keyword_id}", response_model=KeywordRead)
async def get_keyword(
    keyword_id: int,
    db: AsyncSession = Depends(get_db),
):
    keyword = await db.get(Keyword, keyword_id)

    if keyword is None:
        raise HTTPException(status_code=404, detail="Keyword not found")

    return keyword


@router.patch("/{keyword_id}", response_model=KeywordRead)
async def update_keyword(
    keyword_id: int,
    data: KeywordUpdate,
    db: AsyncSession = Depends(get_db),
):
    keyword = await db.get(Keyword, keyword_id)

    if keyword is None:
        raise HTTPException(status_code=404, detail="Keyword not found")

    update_data = data.model_dump(exclude_unset=True)

    if "name" in update_data and update_data["name"] is not None:
        normalized_name = normalize_keyword(update_data["name"])
        duplicate_result = await db.execute(
            select(Keyword).where(
                Keyword.normalized_name == normalized_name,
                Keyword.id != keyword_id,
            )
        )
        duplicate = duplicate_result.scalar_one_or_none()

        if duplicate is not None:
            raise HTTPException(
                status_code=400,
                detail="Ключевое слово с таким названием уже существует",
            )

        keyword.normalized_name = normalized_name

    for field, value in update_data.items():
        setattr(keyword, field, value)

    await db.commit()
    await db.refresh(keyword)

    return keyword


@router.delete("/{keyword_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_keyword(
    keyword_id: int,
    db: AsyncSession = Depends(get_db),
):
    keyword = await db.get(Keyword, keyword_id)

    if keyword is None:
        raise HTTPException(status_code=404, detail="Keyword not found")

    await db.delete(keyword)
    await db.commit()
