from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class AssistantAskRequest(BaseModel):
    question: str = Field(..., min_length=2)
    limit: int = Field(default=5, ge=1, le=10)
    min_similarity: float = Field(default=0.55, ge=0.0, le=1.0)
    detail_percent: int = Field(default=80, ge=80, le=100)


class AssistantSource(BaseModel):
    source_id: str
    publication_id: int
    publication_title: str
    chunk_id: int
    chunk_index: int
    similarity: float


class AssistantAnswerBlock(BaseModel):
    text: str
    source_ids: list[str] = Field(default_factory=list)


class AssistantCatalogItem(BaseModel):
    publication_id: int
    title: str
    year: int | None = None
    authors: list[str] = Field(default_factory=list)
    publication_type: str | None = None
    publication_url: str
    description: str | None = None


class AssistantCatalog(BaseModel):
    total: int
    returned_count: int
    truncated: bool
    items: list[AssistantCatalogItem] = Field(default_factory=list)


AnswerOrigin = Literal["internal", "external", "catalog"]


class AssistantAskResponse(BaseModel):
    question: str
    answer: str
    sources: list[AssistantSource]
    answer_blocks: list[AssistantAnswerBlock]
    answer_origin: AnswerOrigin
    catalog: AssistantCatalog | None = None


class ChatCreate(BaseModel):
    title: str | None = Field(default=None, max_length=200)


class ChatMessageCreate(BaseModel):
    content: str = Field(..., min_length=2, max_length=10000)
    limit: int = Field(default=5, ge=1, le=10)
    min_similarity: float = Field(default=0.55, ge=0.0, le=1.0)
    detail_percent: int = Field(default=80, ge=80, le=100)


class ChatMessageRead(BaseModel):
    id: int
    chat_id: int
    role: str
    content: str
    sources: list[AssistantSource] = Field(default_factory=list)
    answer_blocks: list[AssistantAnswerBlock] = Field(default_factory=list)
    answer_origin: AnswerOrigin | None = None
    catalog: AssistantCatalog | None = None
    created_at: datetime


class ChatRead(BaseModel):
    id: int
    title: str
    created_at: datetime
    updated_at: datetime


class ChatDetail(ChatRead):
    messages: list[ChatMessageRead] = Field(default_factory=list)


class ChatReply(BaseModel):
    chat: ChatRead
    user_message: ChatMessageRead
    assistant_message: ChatMessageRead
