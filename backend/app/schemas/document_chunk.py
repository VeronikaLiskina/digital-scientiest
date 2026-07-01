from datetime import datetime

from pydantic import BaseModel, ConfigDict, field_serializer


class DocumentChunkBase(BaseModel):
    publication_id: int
    chunk_text: str
    page_number: int | None = None
    chunk_index: int
    embedding: list[float] | None = None
    embedding_model: str | None = None
    embedded_at: datetime | None = None


class DocumentChunkCreate(DocumentChunkBase):
    pass


class DocumentChunkUpdate(BaseModel):
    chunk_text: str | None = None
    page_number: int | None = None
    chunk_index: int | None = None

    model_config = ConfigDict(extra="forbid")


class DocumentChunkRead(DocumentChunkBase):
    id: int

    model_config = ConfigDict(from_attributes=True)

    @field_serializer("embedding")
    def serialize_embedding(self, embedding: list[float] | None) -> list[float] | None:
        if embedding is None:
            return None

        return [round(float(value), 7) for value in embedding]
