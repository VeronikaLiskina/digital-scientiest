import pytest

from app.repositories.semantic_search_repository import (
    HYBRID_TOP_K,
    SemanticSearchRepository,
    extract_exact_search_terms,
    reciprocal_rank_fusion,
)


@pytest.fixture(autouse=True)
async def prepare_test_database():
    """Pure hybrid-ranking tests do not require PostgreSQL."""

    yield


def _chunk(chunk_id: int) -> dict:
    return {
        "chunk_id": chunk_id,
        "publication_id": chunk_id,
        "chunk_index": 0,
        "text": f"Chunk {chunk_id}",
        "publication_title": f"Publication {chunk_id}",
        "similarity": 0.9,
    }


def test_exact_scientific_terms_are_preserved_for_full_text_search():
    terms = extract_exact_search_terms(
        "Fe2O3 14,7 %, DOI 10.1234/ABC.567 и ГОСТ 123-45"
    )

    assert "fe2o3" in terms
    assert "14,7" in terms
    assert "10.1234/abc.567" in terms
    assert "гост 123-45" in terms


def test_chunk_ranked_high_in_both_searches_rises_after_rrf():
    vector_only = _chunk(1)
    both = _chunk(2)
    text_only = _chunk(3)

    results = reciprocal_rank_fusion(
        [vector_only, both],
        [both, text_only],
    )

    assert [result["chunk_id"] for result in results] == [2, 1, 3]
    assert results[0]["vector_rank"] == 2
    assert results[0]["text_rank"] == 1


def test_rrf_deduplicates_repeated_chunk_ids():
    duplicate = _chunk(7)

    results = reciprocal_rank_fusion(
        [duplicate, duplicate],
        [duplicate, duplicate],
    )

    assert [result["chunk_id"] for result in results] == [7]


@pytest.mark.asyncio
async def test_semantically_similar_chunk_is_returned_by_vector_search():
    class Mappings:
        @staticmethod
        def all():
            return [
                {
                    "chunk_id": 5,
                    "publication_id": 2,
                    "chunk_index": 0,
                    "text": "Карбонатиты содержат редкоземельные элементы.",
                    "publication_title": "Карбонатитовый массив",
                    "distance": 0.08,
                }
            ]

    class Result:
        @staticmethod
        def mappings():
            return Mappings()

    class Session:
        async def execute(self, _statement):
            return Result()

    results = await SemanticSearchRepository(Session()).search_vector_chunks(
        query_embedding=[0.1] * 768,
        embedding_model="intfloat/multilingual-e5-base",
    )

    assert [result["chunk_id"] for result in results] == [5]
    assert results[0]["similarity"] == pytest.approx(0.92)


@pytest.mark.asyncio
async def test_vector_search_survives_empty_full_text_results():
    vector_results = [_chunk(1), _chunk(2)]

    class StubRepository(SemanticSearchRepository):
        async def search_vector_chunks(self, *_args, **_kwargs):
            return vector_results

        async def search_full_text_chunks(self, *_args, **_kwargs):
            return []

    results = await StubRepository(object()).search_chunks(
        query_embedding=[0.0] * 768,
        embedding_model="intfloat/multilingual-e5-base",
        query_text="точный термин",
    )

    assert [result["chunk_id"] for result in results] == [1, 2]
    assert all(result["text_rank"] is None for result in results)


def test_hybrid_candidate_pool_never_exceeds_twenty_chunks():
    vector_results = [_chunk(chunk_id) for chunk_id in range(1, 31)]
    text_results = [_chunk(chunk_id) for chunk_id in range(31, 61)]

    results = reciprocal_rank_fusion(vector_results, text_results)

    assert len(results) == HYBRID_TOP_K == 20
