from pydantic import BaseModel, ConfigDict, Field


class SourceFileBase(BaseModel):
    file_name: str
    file_path: str
    file_type: str
    file_hash: str | None = None
    pdf_quality: str | None = None
    has_figures: bool = False
    has_tables: bool = False
    processing_status: str = "new"
    processing_task_id: str | None = None
    comment: str | None = None


class SourceFileCreate(SourceFileBase):
    pass


class SourceFileUpdate(BaseModel):
    file_name: str | None = None
    file_path: str | None = None
    file_type: str | None = None
    file_hash: str | None = None
    pdf_quality: str | None = None
    has_figures: bool | None = None
    has_tables: bool | None = None
    processing_status: str | None = None
    processing_task_id: str | None = None
    comment: str | None = None


class SourceFileRead(SourceFileBase):
    id: int

    model_config = ConfigDict(from_attributes=True)


class PdfProcessingTaskRead(BaseModel):
    task_id: str | None
    source_file_id: int
    status: str


class CatalogMatchRead(BaseModel):
    id: int
    name: str
    extracted_name: str


class ExtractedPublicationMetadataRead(BaseModel):
    title: str | None = None
    title_source: str = "unknown"
    title_confidence: str = "low"
    title_warning: str | None = None
    year: int | None = None
    language: str | None = None
    publication_type: str | None = "article"
    doi: str | None = None

    # Все извлеченные значения после нормализации.
    authors: list[str] = Field(default_factory=list)
    keywords: list[str] = Field(default_factory=list)
    topics: list[str] = Field(default_factory=list)

    # Уже существующие записи справочников. Frontend может сразу отметить эти id
    # в MultiSelect, не создавая дубли.
    matched_authors: list[CatalogMatchRead] = Field(default_factory=list)
    matched_author_ids: list[int] = Field(default_factory=list)
    new_authors: list[str] = Field(default_factory=list)

    matched_keywords: list[CatalogMatchRead] = Field(default_factory=list)
    matched_keyword_ids: list[int] = Field(default_factory=list)
    new_keywords: list[str] = Field(default_factory=list)

    matched_topics: list[CatalogMatchRead] = Field(default_factory=list)
    matched_topic_ids: list[int] = Field(default_factory=list)
    new_topics: list[str] = Field(default_factory=list)


class SourceFileMetadataPreview(BaseModel):
    status: str
    file_hash: str
    review_status: str = "manual_entry"
    duplicate_source_file_id: int | None = None
    message: str | None = None
    extracted: ExtractedPublicationMetadataRead | None = None
