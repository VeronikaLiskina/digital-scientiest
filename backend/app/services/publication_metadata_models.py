from dataclasses import dataclass


@dataclass
class ExtractedPublicationMetadata:
    title: str | None
    year: int | None
    language: str | None
    publication_type: str | None
    doi: str | None
    authors: list[str]
    keywords: list[str]
    topics: list[str]
    title_source: str = "unknown"
    title_confidence: str = "low"
    title_warning: str | None = None
    keywords_source: str = "none"
    authors_source: str = "native"


@dataclass
class PageText:
    number: int
    text: str
    lines: list[str]
    source: str = "native"
    layout_title: str | None = None
    author_lines: list[str] | None = None


@dataclass
class TitleMatch:
    title: str
    page_index: int
    line_index: int | None
    score: int
    source: str = "pdf"
    from_layout: bool = False
