import pytest
from sqlalchemy import select

from app.models.document_chunk import DocumentChunk
from app.models.processing_log import ProcessingLog
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
        await session.refresh(publication)
        publication_status = publication.status

    assert result["chunks_created"] == 1
    assert len(chunks) == 1
    assert "\x00" not in chunks[0].chunk_text
    assert chunks[0].embedding is not None
    assert chunks[0].embedding_model == "fake-embedding-model"
    assert chunks[0].embedded_at is not None
    assert publication_status == "processed"


@pytest.mark.asyncio
async def test_process_pdf_file_uses_semantic_chunking(monkeypatch, tmp_path):
    pdf_path = tmp_path / "publication.pdf"
    pdf_path.write_bytes(b"%PDF-1.4")

    def fake_extract_text_blocks(file_path):
        assert file_path == pdf_path
        return [
            TextBlock(
                page_number=2,
                section_title="Results",
                text="First semantic unit.\n\nSecond semantic unit.",
            )
        ]

    async def fake_split_text_into_semantic_chunks(text, embedding_service):
        assert text == "First semantic unit.\n\nSecond semantic unit."
        assert isinstance(embedding_service, FakeEmbeddingService)
        return ["First semantic unit.", "Second semantic unit."]

    monkeypatch.setattr(
        pdf_processing,
        "extract_text_blocks",
        fake_extract_text_blocks,
    )
    monkeypatch.setattr(
        pdf_processing,
        "split_text_into_semantic_chunks",
        fake_split_text_into_semantic_chunks,
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
            title="Publication for semantic chunking",
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
                select(DocumentChunk)
                .where(DocumentChunk.publication_id == publication.id)
                .order_by(DocumentChunk.chunk_index)
            )
        ).scalars().all()

    assert result["chunks_created"] == 2
    assert len(chunks) == 2
    assert "First semantic unit." in chunks[0].chunk_text
    assert "Second semantic unit." in chunks[1].chunk_text


@pytest.mark.asyncio
async def test_split_text_block_filters_numeric_table_noise(monkeypatch):
    async def fake_split_text_into_semantic_chunks(text, embedding_service):
        assert "51.68" not in text
        assert "Continuation of table" not in text
        assert "Magmatic rocks" in text
        return []

    monkeypatch.setattr(
        pdf_processing,
        "split_text_into_semantic_chunks",
        fake_split_text_into_semantic_chunks,
    )

    text = (
        "Magmatic rocks of the studied area show clear geochemical trends. "
        "The samples are grouped by petrographic features and field position.\n"
        "SiO2 51.68 51.55 48.49 51.89 48.52 55.54 53.58 48.59 47.08 "
        "51.15 51.94 50.40 50.90 50.05 49.90 49.00\n"
        "Al2O3 13.95 14.25 14.76 14.28 15.46 14.15 13.85 15.45 13.66 "
        "13.79 14.58 14.05 14.60 14.50\n"
        "Continuation of table 1\n"
        "These observations are used below to compare the samples with the "
        "regional volcanic record."
    )

    chunks = await pdf_processing.split_text_block_into_chunks(
        text,
        FakeEmbeddingService(),
    )

    assert len(chunks) == 1
    assert "Magmatic rocks" in chunks[0]
    assert "regional volcanic record" in chunks[0]
    assert "SiO2 51.68" not in chunks[0]
    assert "Al2O3 13.95" not in chunks[0]
    assert "Continuation of table" not in chunks[0]


@pytest.mark.asyncio
async def test_process_pdf_file_logs_processing_failure(monkeypatch, tmp_path):
    pdf_path = tmp_path / "publication.pdf"
    pdf_path.write_bytes(b"%PDF-1.4")

    def fake_extract_text_blocks(file_path):
        assert file_path == pdf_path
        raise RuntimeError("boom")

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
            title="Publication for failure logging",
            year=2026,
            language="en",
            publication_type="article",
            status="draft",
        )
        session.add(publication)
        await session.commit()

        with pytest.raises(RuntimeError, match="boom"):
            await process_pdf_file(
                db=session,
                source_file_id=source_file.id,
                embedding_service=FakeEmbeddingService(),
            )

        updated_source_file = await session.get(SourceFile, source_file.id)
        assert updated_source_file.processing_status == "error"
        await session.refresh(publication)
        assert publication.status == "review"

        logs = (
            await session.execute(
                select(ProcessingLog).where(
                    ProcessingLog.source_file_id == source_file.id
                )
            )
        ).scalars().all()

    assert any(
        log.step_name == "processing_started" and log.status == "info"
        for log in logs
    )
    assert any(
        log.step_name == "processing_failed"
        and log.status == "error"
        and log.error_message == "boom"
        for log in logs
    )
    assert not any(
        log.step_name == "processing_finished" and log.status == "success"
        for log in logs
    )
