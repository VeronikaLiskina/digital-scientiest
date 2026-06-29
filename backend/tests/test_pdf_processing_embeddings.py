import pytest
from sqlalchemy import select

from app.models.document_chunk import DocumentChunk
from app.models.publication import Publication
from app.models.source_file import SourceFile
from app.services import pdf_processing
from app.services.pdf_processing import TextBlock, process_pdf_file
from conftest import TestingSessionLocal


class FakeEmbeddingService:
    model_name = "fake-embedding-model"

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        return [[0.1] * 768 for _ in texts]

    def embed_text(self, text: str) -> list[float]:
        return [0.1] * 768


@pytest.mark.asyncio
async def test_process_pdf_file_saves_embeddings_and_cleans_chunk_text(
    monkeypatch,
    tmp_path,
):
    pdf_path = tmp_path / "publication.pdf"
    pdf_path.write_bytes(b"%PDF-1.4")

    def fake_extract_text_blocks(file_path):
        assert file_path == pdf_path
        return [
            TextBlock(
                page_number=1,
                section_title="Introduction",
                text="Text with NUL \x00 and magmatism",
            )
        ]

    monkeypatch.setattr(
        pdf_processing,
        "extract_text_blocks",
        fake_extract_text_blocks,
    )

    async with TestingSessionLocal() as session:
        source_file = SourceFile(
            file_name="publication.pdf",
            file_path=str(pdf_path),
            file_type="application/pdf",
            processing_status="new",
        )
        session.add(source_file)
        await session.flush()

        publication = Publication(
            source_file_id=source_file.id,
            title="Publication for embeddings",
            year=2026,
            language="en",
            publication_type="article",
            status="draft",
        )
        session.add(publication)
        await session.commit()

        result = await process_pdf_file(
            db=session,
            source_file_id=source_file.id,
            embedding_service=FakeEmbeddingService(),
        )

        chunks = (
            await session.execute(
                select(DocumentChunk).where(
                    DocumentChunk.publication_id == publication.id
                )
            )
        ).scalars().all()

    assert result["chunks_created"] == 1
    assert len(chunks) == 1
    assert "\x00" not in chunks[0].chunk_text
    assert chunks[0].embedding is not None
    assert chunks[0].embedding_model == "fake-embedding-model"
    assert chunks[0].embedded_at is not None
