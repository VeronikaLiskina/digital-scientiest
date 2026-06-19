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
    comment: str | None = None


class SourceFileRead(SourceFileBase):
    id: int

    model_config = ConfigDict(from_attributes=True)


class ExtractedPublicationMetadataRead(BaseModel):
    title: str | None = None
    year: int | None = None
    language: str | None = None
    publication_type: str | None = "article"
    doi: str | None = None
    authors: list[str] = Field(default_factory=list)
    keywords: list[str] = Field(default_factory=list)
    topics: list[str] = Field(default_factory=list)


class SourceFileMetadataPreview(BaseModel):
    status: str
    file_hash: str
    duplicate_source_file_id: int | None = None
    message: str | None = None
    extracted: ExtractedPublicationMetadataRead | None = None
