from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.source_file import ExtractedPublicationMetadataRead


class ImportItemRead(BaseModel):
    id: int
    batch_id: int
    source_file_id: int | None = None
    publication_id: int | None = None
    original_file_name: str
    status: str
    processing_status: str | None = None
    error_message: str | None = None
    extracted_metadata: ExtractedPublicationMetadataRead | None = None
    title: str | None = None
    title_source: str | None = None
    title_confidence: str | None = None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class ImportBatchRead(BaseModel):
    id: int
    status: str
    total_files: int
    processed_count: int
    needs_review_count: int
    saved_count: int
    duplicate_count: int
    error_count: int
    created_at: datetime
    updated_at: datetime
    items: list[ImportItemRead] = Field(default_factory=list)

    model_config = ConfigDict(from_attributes=True)
