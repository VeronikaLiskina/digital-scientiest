import pytest
from sqlalchemy import select

from app.models.document_chunk import DocumentChunk
from app.models.publication import Publication
from app.repositories.semantic_search_repository import SemanticSearchRepository
from app.scripts.rebuild_embeddings import rebuild_embeddings
from conftest import TestingSessionLocal


@pytest.mark.asyncio
async def test_full_text_search_finds_exact_fe2o3_value():
    async with TestingSessionLocal() as session:
        publication = Publication(
            title="Геохимия железных руд",
            language="ru",
            status="processed",
        )
        session.add(publication)
        await session.flush()
        session.add_all(
            [
                DocumentChunk(
                    publication_id=publication.id,
                    chunk_index=0,
                    chunk_text="Содержание Fe2O3 в пробе составляет 14,7 %.",
                ),
                DocumentChunk(
                    publication_id=publication.id,
                    chunk_index=1,
                    chunk_text="Содержание SiO2 в другой пробе составляет 52,1 %.",
                ),
            ]
        )
        await session.commit()

        results = await SemanticSearchRepository(session).search_full_text_chunks(
            "Найди точное значение Fe2O3 14,7 %",
        )

    assert results
    assert results[0]["chunk_index"] == 0
    assert "Fe2O3" in results[0]["text"]
    assert "14,7 %" in results[0]["text"]


@pytest.mark.asyncio
async def test_full_text_search_finds_doi_author_deposit_and_standard():
    async with TestingSessionLocal() as session:
        publication = Publication(
            title="Стандарты анализа месторождения",
            language="ru",
            status="processed",
        )
        session.add(publication)
        await session.flush()
        target = DocumentChunk(
            publication_id=publication.id,
            chunk_index=0,
            chunk_text=(
                "Иванов исследовал Ермаковское месторождение по ГОСТ 123-45; "
                "результаты опубликованы под DOI 10.1234/ORE.567."
            ),
        )
        session.add(target)
        await session.commit()

        repository = SemanticSearchRepository(session)
        queries = [
            "Иванов",
            "Ермаковское месторождение",
            "ГОСТ 123-45",
            "10.1234/ORE.567",
        ]
        result_sets = [
            await repository.search_full_text_chunks(query)
            for query in queries
        ]

    assert all(results and results[0]["chunk_id"] == target.id for results in result_sets)


@pytest.mark.asyncio
async def test_reindex_leaves_embeddings_from_only_one_model():
    class FakeEmbeddingService:
        model_name = "intfloat/multilingual-e5-base"

        @staticmethod
        def embed_documents(texts):
            return [[0.1] * 768 for _ in texts]

    async with TestingSessionLocal() as session:
        publication = Publication(title="Переиндексация", status="processed")
        session.add(publication)
        await session.flush()
        session.add_all(
            [
                DocumentChunk(
                    publication_id=publication.id,
                    chunk_index=index,
                    chunk_text=f"Фрагмент {index}",
                    embedding=[0.2] * 768,
                    embedding_model=(
                        "sentence-transformers/paraphrase-multilingual-mpnet-base-v2"
                        if index < 2
                        else "intfloat/multilingual-e5-base"
                    ),
                )
                for index in range(3)
            ]
        )
        await session.commit()

    await rebuild_embeddings(
        model_name="intfloat/multilingual-e5-base",
        rebuild_batch_size=2,
        session_factory=TestingSessionLocal,
        embedding_service=FakeEmbeddingService(),
    )

    async with TestingSessionLocal() as session:
        chunks = list((await session.execute(select(DocumentChunk))).scalars())

    assert chunks
    assert all(chunk.embedding is not None for chunk in chunks)
    assert {chunk.embedding_model for chunk in chunks} == {
        "intfloat/multilingual-e5-base"
    }
