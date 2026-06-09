from pydantic import BaseModel, ConfigDict

from app.schemas.author import AuthorRead
from app.schemas.keyword import KeywordRead
from app.schemas.topic import TopicRead


class PublicationBase(BaseModel):
    title: str
    year: int | None = None
    language: str | None = None
    publication_type: str | None = None
    doi: str | None = None
    status: str = "draft"
    source_file_id: int | None = None


class PublicationCreate(PublicationBase):
    author_ids: list[int] = []
    topic_ids: list[int] = []
    keyword_ids: list[int] = []


class PublicationUpdate(BaseModel):
    title: str | None = None
    year: int | None = None
    language: str | None = None
    publication_type: str | None = None
    doi: str | None = None
    status: str | None = None
    source_file_id: int | None = None

    author_ids: list[int] | None = None
    topic_ids: list[int] | None = None
    keyword_ids: list[int] | None = None


class PublicationRead(PublicationBase):
    id: int
    authors: list[AuthorRead] = []
    topics: list[TopicRead] = []
    keywords: list[KeywordRead] = []

    model_config = ConfigDict(from_attributes=True)