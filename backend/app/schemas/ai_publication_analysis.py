from pydantic import BaseModel, Field


class AIPublicationFieldEvidence(BaseModel):
    confidence: float | None = None
    evidence: str | None = None
    page: int | None = None


class AIPublicationAnalysisResponse(BaseModel):
    title: str | None = None
    authors: list[str] = Field(default_factory=list)
    year: int | None = None
    doi: str | None = None
    keywords: list[str] = Field(default_factory=list)
    field_metadata: dict[str, AIPublicationFieldEvidence] = Field(
        default_factory=dict
    )
