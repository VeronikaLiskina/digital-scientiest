from pathlib import Path

import pytest

from benchmarks.compare_embedding_models import calculate_metrics, load_dataset


def test_curated_embedding_dataset_has_valid_relevance_judgments():
    dataset = load_dataset(
        Path(__file__).parents[1] / "benchmarks" / "embedding_retrieval.json"
    )

    assert len(dataset["questions"]) >= 10
    assert len(dataset["chunks"]) >= 20


def test_calculate_retrieval_metrics():
    metrics = calculate_metrics(
        rankings=[
            ["noise", "relevant-a", "relevant-b"],
            ["relevant-c", "noise"],
        ],
        relevant_chunk_ids=[{"relevant-a", "relevant-b"}, {"relevant-c"}],
    )

    assert metrics.recall_at_5 == pytest.approx(1.0)
    assert metrics.recall_at_10 == pytest.approx(1.0)
    assert metrics.mrr == pytest.approx(0.75)
