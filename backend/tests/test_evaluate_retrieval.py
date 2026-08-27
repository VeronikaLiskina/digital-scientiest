import json

import pytest

from scripts.evaluate_retrieval import (
    EvaluationItem,
    build_report,
    calculate_metrics,
    evidence_group_recall_at_k,
    hit_at_k,
    load_dataset,
    reciprocal_rank,
)


@pytest.fixture(autouse=True)
async def prepare_test_database():
    yield


def item(
    item_id: str,
    *,
    relevant_ids: set[int],
    answerable: bool,
    category: str = "semantic",
) -> EvaluationItem:
    return EvaluationItem(
        id=item_id,
        question=f"Question {item_id}",
        relevant_chunk_ids=frozenset(relevant_ids),
        answerable=answerable,
        category=category,
    )


def test_hit_at_k_and_reciprocal_rank_use_first_relevant_chunk():
    ranking = [10, 20, 30, 40, 50, 60]
    relevant = frozenset({30, 60})

    assert hit_at_k(ranking, relevant, 2) is False
    assert hit_at_k(ranking, relevant, 5) is True
    assert reciprocal_rank(ranking, relevant) == pytest.approx(1 / 3)


def test_metrics_separate_retrieval_quality_and_answerability_errors():
    items = [
        item("q1", relevant_ids={11}, answerable=True),
        item("q2", relevant_ids={22}, answerable=True),
        item("q3", relevant_ids=set(), answerable=False, category="no_answer"),
        item("q4", relevant_ids=set(), answerable=False, category="no_answer"),
    ]
    rankings = [[99, 11], [], [77], []]

    metrics = calculate_metrics(items, rankings)

    assert metrics.recall_at_5 == 0.5
    assert metrics.recall_at_10 == 0.5
    assert metrics.mrr == 0.25
    assert metrics.answerability_accuracy == 0.5
    assert metrics.false_positives == 1
    assert metrics.false_negatives == 1


def test_evidence_group_recall_requires_each_composite_answer_aspect():
    composite = EvaluationItem(
        id="q-composite",
        question="Which methods?",
        relevant_chunk_ids=frozenset({146, 3090}),
        answerable=True,
        category="semantic",
        relevant_chunk_groups=(frozenset({146}), frozenset({3090})),
    )

    assert hit_at_k([146], composite.relevant_chunk_ids, 5) is True
    assert evidence_group_recall_at_k([146], composite, 5) == 0.5
    assert evidence_group_recall_at_k([146, 3090], composite, 5) == 1.0


def test_load_dataset_validates_answerability_contract(tmp_path):
    dataset = tmp_path / "dataset.json"
    dataset.write_text(
        json.dumps(
            [
                {
                    "id": "q1",
                    "question": "Question",
                    "relevant_chunk_ids": [],
                    "answerable": True,
                    "category": "semantic",
                }
            ]
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="disagree"):
        load_dataset(dataset)


def test_report_contains_stage_metrics_categories_and_failure_details(tmp_path):
    items = [
        item("q1", relevant_ids={10}, answerable=True),
        item("q2", relevant_ids=set(), answerable=False, category="no_answer"),
    ]
    stage_results = {
        "relevance_gate": [
            [
                {
                    "chunk_id": 99,
                    "publication_id": 1,
                    "similarity": 0.8,
                    "rrf_score": 0.03,
                }
            ],
            [],
        ]
    }

    report = build_report(
        dataset_path=tmp_path / "dataset.json",
        items=items,
        stage_results=stage_results,
        candidate_limit=20,
        min_similarity=0.55,
    )

    stage = report["stages"]["relevance_gate"]
    assert stage["overall"]["Recall@5"] == 0.0
    assert stage["overall"]["answerability_accuracy"] == 1.0
    assert set(stage["by_category"]) == {"no_answer", "semantic"}
    assert stage["failures"] == [
        {
            "id": "q1",
            "question": "Question q1",
            "category": "semantic",
            "answerable": True,
            "predicted_answerable": True,
            "expected_chunk_ids": [10],
            "expected_chunk_groups": [],
            "evidence_group_recall_at_10": 0.0,
            "retrieved": [
                {
                    "chunk_id": 99,
                    "publication_id": 1,
                    "chunk_index": None,
                    "publication_title": None,
                    "similarity": 0.8,
                    "fts_score": None,
                    "rrf_score": 0.03,
                    "reranker_score": None,
                    "vector_rank": None,
                    "fts_rank": None,
                    "text_preview": "",
                    "rank": 1,
                }
            ],
        }
    ]
