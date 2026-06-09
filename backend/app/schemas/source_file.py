from pydantic import BaseModel, ConfigDict


class SourceFileBase(BaseModel):
    file_name: str
    file_path: str
    file_type: str
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
    pdf_quality: str | None = None
    has_figures: bool | None = None
    has_tables: bool | None = None
    processing_status: str | None = None
    comment: str | None = None


class SourceFileRead(SourceFileBase):
    id: int

    model_config = ConfigDict(from_attributes=True)