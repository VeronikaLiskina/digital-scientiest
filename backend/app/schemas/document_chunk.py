from pydantic import BaseModel, ConfigDict


class DocumentChunkBase(BaseModel):
    publication_id: int
    chunk_text: str
    page_number: int | None = None
    chunk_index: int
    embedding: list[float] | None = None


class DocumentChunkCreate(DocumentChunkBase):
    pass


class DocumentChunkUpdate(BaseModel):
    chunk_text: str | None = None
    page_number: int | None = None
    chunk_index: int | None = None
    embedding: list[float] | None = None


class DocumentChunkRead(DocumentChunkBase):
    id: int

    model_config = ConfigDict(from_attributes=True)