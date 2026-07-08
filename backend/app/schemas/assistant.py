from pydantic import BaseModel, Field


class AssistantAskRequest(BaseModel):
    question: str = Field(..., min_length=2)
    limit: int = Field(default=5, ge=1, le=10)
    min_similarity: float = Field(default=0.55, ge=0.0, le=1.0)


class AssistantSource(BaseModel):
    publication_id: int
    publication_title: str | None = None
    chunk_id: int
    chunk_index: int | None = None
    text: str 
    similarity: float


class AssistantAskResponse(BaseModel):
    question: str
    answer: str
    sources: list[AssistantSource]
