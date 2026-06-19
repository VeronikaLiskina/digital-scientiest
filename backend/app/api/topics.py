from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.database import get_db
from app.models.topic import Topic
from app.schemas.topic import TopicCreate, TopicRead, TopicUpdate
from app.services.topic_resolver import get_or_create_topic
from app.utils.normalization import normalize_topic


router = APIRouter(prefix="/topics", tags=["Topics"])


@router.post("", response_model=TopicRead, status_code=status.HTTP_201_CREATED)
async def create_topic(
    data: TopicCreate,
    db: AsyncSession = Depends(get_db),
):
    topic = await get_or_create_topic(
        db=db,
        name=data.name,
        description=data.description,
    )
    await db.commit()
    await db.refresh(topic)
    return topic


@router.get("", response_model=list[TopicRead])
async def get_topics(
    search: str | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
):
    query = select(Topic).order_by(Topic.name)

    if search:
        query = query.where(Topic.name.ilike(f"%{search}%"))

    result = await db.execute(query)
    return result.scalars().all()


@router.get("/{topic_id}", response_model=TopicRead)
async def get_topic(
    topic_id: int,
    db: AsyncSession = Depends(get_db),
):
    topic = await db.get(Topic, topic_id)

    if topic is None:
        raise HTTPException(status_code=404, detail="Topic not found")

    return topic


@router.patch("/{topic_id}", response_model=TopicRead)
async def update_topic(
    topic_id: int,
    data: TopicUpdate,
    db: AsyncSession = Depends(get_db),
):
    topic = await db.get(Topic, topic_id)

    if topic is None:
        raise HTTPException(status_code=404, detail="Topic not found")

    update_data = data.model_dump(exclude_unset=True)

    if "name" in update_data and update_data["name"] is not None:
        normalized_name = normalize_topic(update_data["name"])
        duplicate_result = await db.execute(
            select(Topic).where(
                Topic.normalized_name == normalized_name,
                Topic.id != topic_id,
            )
        )
        duplicate = duplicate_result.scalar_one_or_none()

        if duplicate is not None:
            raise HTTPException(
                status_code=400,
                detail="Тема с таким названием уже существует",
            )

        topic.normalized_name = normalized_name

    for field, value in update_data.items():
        setattr(topic, field, value)

    await db.commit()
    await db.refresh(topic)

    return topic


@router.delete("/{topic_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_topic(
    topic_id: int,
    db: AsyncSession = Depends(get_db),
):
    topic = await db.get(Topic, topic_id)

    if topic is None:
        raise HTTPException(status_code=404, detail="Topic not found")

    await db.delete(topic)
    await db.commit()
