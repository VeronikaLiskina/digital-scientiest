from datetime import datetime

from pydantic import BaseModel, Field


class AssistantAskRequest(BaseModel):
    question: str = Field(..., min_length=2)
    limit: int = Field(default=5, ge=1, le=10)
    min_similarity: float = Field(default=0.55, ge=0.0, le=1.0)


class AssistantSource(BaseModel):
    publication_id: int
    publication_title: str
    chunk_id: int
    chunk_index: int
    similarity: float


class AssistantAskResponse(BaseModel):
    question: str
    answer: str
    sources: list[AssistantSource]


class ChatCreate(BaseModel):
    title: str | None = Field(default=None, max_length=200)


class ChatMessageCreate(BaseModel):
    content: str = Field(..., min_length=2, max_length=10000)
    limit: int = Field(default=5, ge=1, le=10)
    min_similarity: float = Field(default=0.55, ge=0.0, le=1.0)


class ChatMessageRead(BaseModel):
    id: int
    chat_id: int
    role: str
    content: str
    sources: list[AssistantSource] = Field(default_factory=list)
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
