import pytest

from app.repositories.semantic_search_repository import (
    HYBRID_TOP_K,
    SemanticSearchRepository,
    extract_expanded_full_text_terms,
    extract_exact_search_terms,
    extract_full_text_terms,
    reciprocal_rank_fusion,
)
from app.services.scientific_query_expansion import (
    extract_geochronology_aspect_terms,
    extract_scientific_entity_terms,
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


def test_generic_uppercase_acronyms_are_not_treated_as_chemical_formulas():
    assert extract_exact_search_terms("Какой DOI указан у статьи?") == []


def test_russian_scientific_query_uses_lemmas_and_transliteration_without_dictionary():
    terms = extract_expanded_full_text_terms(
        "Возрастной пик детритовых цирконов Томторской свиты"
    )

    assert not {"age", "peak", "detrital", "zircon", "formation"} & set(terms)
    assert "tomtor" in terms
    assert "murun" in extract_expanded_full_text_terms("массив Малый Мурун")


def test_short_place_name_is_transliterated_without_manual_translation():
    question = "Какие два возрастных этапа вулканизма выделены в районе реки Уда?"
    terms = set(extract_expanded_full_text_terms(question))
    entity_terms = set(
        extract_scientific_entity_terms(
            question,
            stopwords=set(),
        )
    )

    assert "uda" in terms
    assert not {"age", "stage", "episode", "volcanism", "area", "river"} & terms
    assert "uda" in entity_terms


def test_scientific_entity_terms_transliterate_names_without_alias_dictionary():
    stopwords: set[str] = set()

    assert "murun" in extract_scientific_entity_terms(
        "массив Малый Мурун",
        stopwords=stopwords,
    )
    assert "udzhinskogo" in extract_scientific_entity_terms(
        "Уджинского палеорифта",
        stopwords=stopwords,
    )


def test_geochronology_method_query_adds_direct_dating_markers():
    terms = extract_expanded_full_text_terms(
        "Какие геохронологические методы использовались для определения возраста?"
    )
    entity_terms = extract_scientific_entity_terms(
        "Какие геохронологические методы использовались для определения возраста?",
        stopwords=set(),
    )

    assert "isotopic" not in terms
    assert "geokhronologicheskiy" in terms
    assert {"радиоизотопн", "shrimp", "40ar/39ar", "206pb/238u"} <= set(
        entity_terms
    )


def test_geochronology_method_query_preserves_magmatic_and_ore_aspects():
    entity_terms = extract_scientific_entity_terms(
        "Какие методы датирования магматических и рудных процессов применялись?",
        stopwords=set(),
    )

    assert {"magmatic", "magmatism", "ore", "mineralisation", "mineralization"} <= set(
        entity_terms
    )
    assert extract_geochronology_aspect_terms(
        "Какие методы датирования магматических и рудных процессов применялись?"
    ) == ["magmatic", "magmatism", "ore", "mineralisation", "mineralization"]


def test_full_text_terms_drop_function_words_and_generic_query_verbs():
    terms = extract_full_text_terms(
        "Какие методы использовались для определения возраста в пределах кратона?"
    )

    assert "для" not in terms
    assert "в" not in terms
    assert "использовались" not in terms
    assert "пределах" not in terms
    assert {"методы", "определения", "возраста", "кратона"} <= set(terms)


def test_full_text_terms_drop_publication_mention_meta_intent():
    terms = extract_full_text_terms(
        "Базаниты — что это и в каких публикациях упоминается?"
    )

    assert "базаниты" in terms
    assert "упоминается" not in terms


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


def test_rrf_retains_top_fifteen_candidates_from_each_retriever():
    shared = [_chunk(chunk_id) for chunk_id in range(100, 120)]
    vector_only = [_chunk(chunk_id) for chunk_id in range(1, 16)]
    text_only = [_chunk(chunk_id) for chunk_id in range(51, 66)]

    results = reciprocal_rank_fusion(
        [*vector_only, *shared],
        [*text_only, *shared],
        limit=30,
    )
    result_ids = {result["chunk_id"] for result in results}

    assert {result["chunk_id"] for result in vector_only} <= result_ids
    assert {result["chunk_id"] for result in text_only} <= result_ids
    assert len(results) == 30


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


def test_hybrid_candidate_pool_never_exceeds_thirty_chunks():
    vector_results = [_chunk(chunk_id) for chunk_id in range(1, 51)]
    text_results = [_chunk(chunk_id) for chunk_id in range(51, 101)]

    results = reciprocal_rank_fusion(vector_results, text_results)

    assert len(results) == HYBRID_TOP_K == 30
