from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.database import get_db
from app.models.author import Author
from app.schemas.author import AuthorCreate, AuthorRead, AuthorUpdate
from app.services.author_resolver import get_or_create_author
from app.utils.normalization import normalize_author_name


router = APIRouter(prefix="/authors", tags=["Authors"])


@router.post("", response_model=AuthorRead, status_code=status.HTTP_201_CREATED)
async def create_author(
    data: AuthorCreate,
    db: AsyncSession = Depends(get_db),
):
    author = await get_or_create_author(
        db=db,
        full_name=data.full_name,
        organization=data.organization,
    )
    await db.commit()
    await db.refresh(author)
    return author


@router.get("", response_model=list[AuthorRead])
async def get_authors(
    search: str | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
):
    query = select(Author).order_by(Author.full_name)

    if search:
        query = query.where(Author.full_name.ilike(f"%{search}%"))

    result = await db.execute(query)
    return result.scalars().all()


@router.get("/{author_id}", response_model=AuthorRead)
async def get_author(
    author_id: int,
    db: AsyncSession = Depends(get_db),
):
    author = await db.get(Author, author_id)

    if author is None:
        raise HTTPException(status_code=404, detail="Author not found")

    return author


@router.patch("/{author_id}", response_model=AuthorRead)
async def update_author(
    author_id: int,
    data: AuthorUpdate,
    db: AsyncSession = Depends(get_db),
):
    author = await db.get(Author, author_id)

    if author is None:
        raise HTTPException(status_code=404, detail="Author not found")

    update_data = data.model_dump(exclude_unset=True)

    if "full_name" in update_data and update_data["full_name"] is not None:
        normalized_name = normalize_author_name(update_data["full_name"])
        duplicate_result = await db.execute(
            select(Author).where(
                Author.normalized_name == normalized_name,
                Author.id != author_id,
            )
        )
        duplicate = duplicate_result.scalar_one_or_none()

        if duplicate is not None:
            raise HTTPException(
                status_code=400,
                detail="Автор с таким ФИО уже существует",
            )

        author.normalized_name = normalized_name

    for field, value in update_data.items():
        setattr(author, field, value)

    await db.commit()
    await db.refresh(author)

    return author


@router.delete("/{author_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_author(
    author_id: int,
    db: AsyncSession = Depends(get_db),
):
    author = await db.get(Author, author_id)

    if author is None:
        raise HTTPException(status_code=404, detail="Author not found")

    await db.delete(author)
    await db.commit()
