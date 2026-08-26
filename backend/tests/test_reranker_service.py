import pytest

from app.services.reranker_service import RerankerService


@pytest.fixture(autouse=True)
async def prepare_test_database():
    yield


def make_service(scores: list[float], *, min_score: float = 0.5, top_k: int = 8):
    service = RerankerService.__new__(RerankerService)
    service.min_score = min_score
    service.top_k = top_k
    service._score_pairs = lambda _pairs: scores
    return service


def test_reranker_orders_pairs_and_removes_scores_below_threshold():
    chunks = [
        {"chunk_id": 1, "text": "Первый фрагмент", "similarity": 0.95},
        {"chunk_id": 2, "text": "Второй фрагмент", "similarity": 0.70},
        {"chunk_id": 3, "text": "Третий фрагмент", "similarity": 0.90},
    ]

    ranked = make_service([0.62, 0.94, 0.12]).rerank(
        "Какой фрагмент отвечает на вопрос?",
        chunks,
        limit=8,
    )

    assert [chunk["chunk_id"] for chunk in ranked] == [2, 1]
    assert [chunk["reranker_score"] for chunk in ranked] == [0.94, 0.62]


def test_reranker_honors_configured_top_k_even_for_larger_request_limit():
    chunks = [
        {"chunk_id": index, "text": f"Фрагмент {index}", "similarity": 0.8}
        for index in range(1, 5)
    ]

    ranked = make_service([0.6, 0.9, 0.8, 0.7], top_k=2).rerank(
        "Вопрос",
        chunks,
        limit=4,
    )

    assert [chunk["chunk_id"] for chunk in ranked] == [2, 3]


def test_reranker_diagnostics_keep_below_threshold_scores():
    chunks = [
        {"chunk_id": 1, "text": "first"},
        {"chunk_id": 2, "text": "second"},
    ]

    ranked, scored = make_service([0.2, 0.8]).rerank_with_diagnostics(
        "question",
        chunks,
        limit=8,
    )

    assert [chunk["chunk_id"] for chunk in ranked] == [2]
    assert [chunk["chunk_id"] for chunk in scored] == [2, 1]
    assert scored[0]["reranker_passed_threshold"] is True
    assert scored[1]["reranker_score"] == 0.2
    assert scored[1]["reranker_passed_threshold"] is False


def test_reranker_does_not_depend_on_a_manual_translation_dictionary():
    service = make_service([])
    calls: list[list[tuple[str, str]]] = []

    def score_pairs(pairs):
        calls.append(pairs)
        return [0.8, 0.6]

    service._score_pairs = score_pairs
    chunks = [
        {"chunk_id": 1, "text": "The detrital zircon age peak is 1953 Ma."},
        {"chunk_id": 2, "text": "A different geological result."},
    ]

    ranked, scored = service.rerank_with_diagnostics(
        "Какой возрастной пик детритовых цирконов установлен?",
        chunks,
    )

    assert len(calls) == 1
    assert [chunk["chunk_id"] for chunk in ranked] == [1, 2]
    assert scored[0]["reranker_original_score"] == 0.8
    assert "reranker_bilingual_score" not in scored[0]
    assert scored[0]["reranker_score"] == 0.8


def test_reranker_uses_normalized_intent_for_geochronology_method_evidence():
    service = make_service([])
    calls: list[list[tuple[str, str]]] = []

    def score_pairs(pairs):
        calls.append(pairs)
        if pairs[0][0] == "Какими методами выполнялось радиоизотопное датирование?":
            return [0.93]
        return [0.07, 0.80]

    service._score_pairs = score_pairs
    chunks = [
        {
            "chunk_id": 3090,
            "text": "Радиоизотопное датирование выполнялось 40Ar/39Ar и U-Pb методом SHRIMP.",
        },
        {"chunk_id": 1, "text": "Общий вывод о возрасте магматизма."},
    ]

    ranked, scored = service.rerank_with_diagnostics(
        "Какие геохронологические методы применялись для определения возраста?",
        chunks,
    )

    assert len(calls) == 2
    assert [chunk["chunk_id"] for chunk in ranked] == [3090, 1]
    assert scored[0]["reranker_original_score"] == 0.07
    assert scored[0]["reranker_intent_score"] == 0.93
    assert scored[0]["reranker_score"] == 0.93


def test_reranker_preserves_exact_mentions_for_source_lookup_intent():
    service = make_service([])
    calls: list[list[tuple[str, str]]] = []

    def score_pairs(pairs):
        calls.append(pairs)
        if pairs[0][0] == "базаниты":
            return [0.90, 0.20]
        return [0.10, 0.08]

    service._score_pairs = score_pairs
    chunks = [
        {
            "chunk_id": 1,
            "publication_id": 10,
            "text": "Базаниты являются щелочными магматическими породами.",
        },
        {
            "chunk_id": 2,
            "publication_id": 20,
            "text": "В составе вулканической серии также отмечены базаниты.",
        },
    ]

    ranked, scored = service.rerank_with_diagnostics(
        "Базаниты — что это и в каких публикациях упоминается?",
        chunks,
    )

    assert len(calls) == 2
    assert [chunk["chunk_id"] for chunk in ranked] == [1, 2]
    assert scored[0]["reranker_entity_score"] == 0.90
    assert scored[1]["reranker_entity_score"] == 0.20
    assert scored[1]["reranker_entity_exact_match"] is True
    assert scored[1]["reranker_passed_threshold"] is True


def test_reranker_does_not_score_an_empty_candidate_list():
    service = make_service([])
    service._score_pairs = lambda _pairs: pytest.fail("scoring must not be called")

    assert service.rerank("Вопрос", [], limit=5) == []


@pytest.mark.parametrize("min_score", [-0.01, 1.01])
def test_reranker_rejects_invalid_normalized_threshold(min_score):
    with pytest.raises(ValueError, match="min_score"):
        RerankerService(min_score=min_score)
