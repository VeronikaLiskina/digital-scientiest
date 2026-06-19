from pydantic import BaseModel, ConfigDict, Field

from app.schemas.publication import PublicationRead


class ExtractedPublicationData(BaseModel):
    title: str | None = None
    year: int | None = None
    language: str | None = None
    publication_type: str | None = "article"
    doi: str | None = None
    authors: list[str] = Field(default_factory=list)
    keywords: list[str] = Field(default_factory=list)
    topics: list[str] = Field(default_factory=list)


class PdfBatchImportItem(BaseModel):
    filename: str
    status: str
    source_file_id: int | None = None
    message: str | None = None
    extracted: ExtractedPublicationData | None = None


class ImportPublicationConfirmItem(BaseModel):
    source_file_id: int
    title: str
    year: int | None = None
    language: str | None = "ru"
    publication_type: str | None = "article"
    doi: str | None = None
    status: str = "draft"
    authors: list[str] = Field(default_factory=list)
    keywords: list[str] = Field(default_factory=list)
    topics: list[str] = Field(default_factory=list)


class ImportPublicationConfirmRequest(BaseModel):
    items: list[ImportPublicationConfirmItem]


class ImportPublicationConfirmResult(BaseModel):
    source_file_id: int
    status: str
    publication_id: int | None = None
    message: str | None = None
    publication: PublicationRead | None = None

    model_config = ConfigDict(from_attributes=True)
