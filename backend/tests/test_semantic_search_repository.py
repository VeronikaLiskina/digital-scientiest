import pytest

from app.repositories.semantic_search_repository import SemanticSearchRepository


class EmptyMappings:
    @staticmethod
    def all():
        return []


class EmptyResult:
    @staticmethod
    def mappings():
        return EmptyMappings()


class CapturingSession:
    def __init__(self):
        self.statement = None

    async def execute(self, statement):
        self.statement = statement
        return EmptyResult()


@pytest.mark.asyncio
async def test_semantic_search_filters_vectors_by_active_model():
    session = CapturingSession()
    repository = SemanticSearchRepository(session)

    await repository.search_vector_chunks(
        query_embedding=[0.0] * 768,
        embedding_model="intfloat/multilingual-e5-base",
    )

    compiled = session.statement.compile()
    assert "document_chunks.embedding_model" in str(compiled)
    assert "intfloat/multilingual-e5-base" in compiled.params.values()
