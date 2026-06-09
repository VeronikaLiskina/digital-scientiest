from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.database import get_db
from app.models.topic import Topic
from app.schemas.topic import TopicCreate, TopicRead, TopicUpdate


router = APIRouter(prefix="/topics", tags=["Topics"])


@router.post("", response_model=TopicRead, status_code=status.HTTP_201_CREATED)
async def create_topic(
    data: TopicCreate,
    db: AsyncSession = Depends(get_db),
):
    topic = Topic(**data.model_dump())

    db.add(topic)
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