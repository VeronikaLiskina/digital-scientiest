from __future__ import annotations

import argparse
import asyncio
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sqlalchemy import select

from app.core.config import settings
from app.db.database import async_session_maker
from app.dependencies import get_reranker_service
from app.models.document_chunk import DocumentChunk
from app.repositories.semantic_search_repository import (
    FULL_TEXT_TOP_K,
    HYBRID_TOP_K,
    VECTOR_TOP_K,
    SemanticSearchRepository,
    extract_entity_search_terms,
    extract_exact_search_terms,
    extract_expanded_full_text_terms,
    extract_full_text_terms,
    reciprocal_rank_fusion,
)
from app.services.embedding_service import EmbeddingService
from app.services.source_relevance import (
    diversify_chunks_by_publication,
    explain_source_relevance,
    filter_relevant_sources,
)


ALLOWED_CATEGORIES = {
    "semantic",
    "exact",
    "cross_language",
    "no_answer",
    "short_ambiguous",
}
RETRIEVAL_CATEGORIES = ("semantic", "exact", "cross_language")

# Manual audit trail for answer-equivalent adjacent/duplicate chunks. Keeping
# this next to the evaluator makes ground-truth changes reviewable instead of
# silently broadening the acceptable set.
GROUND_TRUTH_AUDIT = {
    "q002": {144: "Adjacent chunk repeats the complete heat/fluids/metals answer."},
    "q003": {2774: "Russian abstract is answer-equivalent to English chunk 2776."},
    "q004": {2939: "Adjacent metadata chunk explicitly states a felsic source."},
    "q005": {3259: "Russian discussion directly explains the inherited deep-fault control."},
    "q006": {3135: "Adjacent continuation contains the quantitative conformity test."},
    "q012": {3443: "Russian results table contains all three requested Ar-Ar ages."},
    "q017": {3206: "Russian body chunk states >70 km length and 150 m maximum thickness."},
    "q019": {
        3250: "Russian discussion states both 706+/-9 and 395+/-20 Ma events.",
        3260: "Russian conclusion repeats both ages and their interpretation.",
    },
    "q021": {
        3371: "Russian abstract gives the 650-700 km petrological limit.",
        3427: "Russian conclusion repeats the same direct answer.",
    },
}


@dataclass(frozen=True, slots=True)
class EvaluationItem:
    id: str
    question: str
    relevant_chunk_ids: frozenset[int]
    answerable: bool
    category: str
    relevant_chunk_groups: tuple[frozenset[int], ...] = ()


@dataclass(frozen=True, slots=True)
class StageMetrics:
    questions: int
    answerable_questions: int
    recall_at_5: float
    recall_at_10: float
    recall_at_20: float
    recall_at_30: float
    evidence_group_recall_at_5: float
    evidence_group_recall_at_10: float
    mrr: float
    answerability_accuracy: float
    false_positives: int
    false_negatives: int

    def as_dict(self) -> dict[str, int | float]:
        return {
            "questions": self.questions,
            "answerable_questions": self.answerable_questions,
            "Recall@5": self.recall_at_5,
            "Recall@10": self.recall_at_10,
            "Recall@20": self.recall_at_20,
            "Recall@30": self.recall_at_30,
            "EvidenceGroupRecall@5": self.evidence_group_recall_at_5,
            "EvidenceGroupRecall@10": self.evidence_group_recall_at_10,
            "MRR": self.mrr,
            "answerability_accuracy": self.answerability_accuracy,
            "false_positives": self.false_positives,
            "false_negatives": self.false_negatives,
        }


def load_dataset(path: Path) -> list[EvaluationItem]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"Could not read evaluation dataset {path}: {exc}") from exc

    if not isinstance(payload, list) or not payload:
        raise ValueError("Evaluation dataset must be a non-empty JSON array")

    items: list[EvaluationItem] = []
    seen_ids: set[str] = set()
    for index, raw_item in enumerate(payload):
        if not isinstance(raw_item, dict):
            raise ValueError(f"Dataset item at index {index} must be an object")

        item_id = str(raw_item.get("id") or "").strip()
        question = str(raw_item.get("question") or "").strip()
        category = str(raw_item.get("category") or "").strip()
        answerable = raw_item.get("answerable")
        raw_chunk_ids = raw_item.get("relevant_chunk_ids")
        raw_chunk_groups = raw_item.get("relevant_chunk_groups")

        if not item_id or item_id in seen_ids:
            raise ValueError(f"Dataset item IDs must be non-empty and unique: {item_id!r}")
        if not question:
            raise ValueError(f"Question is missing for dataset item {item_id!r}")
        if category not in ALLOWED_CATEGORIES:
            raise ValueError(f"Unsupported category {category!r} for item {item_id!r}")
        if not isinstance(answerable, bool):
            raise ValueError(f"answerable must be boolean for item {item_id!r}")
        if not isinstance(raw_chunk_ids, list) or any(
            not isinstance(chunk_id, int) or isinstance(chunk_id, bool) or chunk_id <= 0
            for chunk_id in raw_chunk_ids
        ):
            raise ValueError(f"Invalid relevant_chunk_ids for item {item_id!r}")

        chunk_ids = frozenset(raw_chunk_ids)
        if len(chunk_ids) != len(raw_chunk_ids):
            raise ValueError(f"Duplicate relevant_chunk_ids for item {item_id!r}")
        if answerable != bool(chunk_ids):
            raise ValueError(
                f"answerable and relevant_chunk_ids disagree for item {item_id!r}"
            )

        chunk_groups: tuple[frozenset[int], ...] = ()
        if raw_chunk_groups is not None:
            if not isinstance(raw_chunk_groups, list) or not raw_chunk_groups:
                raise ValueError(
                    f"relevant_chunk_groups must be a non-empty array for item {item_id!r}"
                )
            parsed_groups: list[frozenset[int]] = []
            for raw_group in raw_chunk_groups:
                if not isinstance(raw_group, list) or not raw_group or any(
                    not isinstance(chunk_id, int)
                    or isinstance(chunk_id, bool)
                    or chunk_id <= 0
                    for chunk_id in raw_group
                ):
                    raise ValueError(
                        f"Invalid relevant_chunk_groups for item {item_id!r}"
                    )
                group = frozenset(raw_group)
                if len(group) != len(raw_group) or not group <= chunk_ids:
                    raise ValueError(
                        f"relevant_chunk_groups must contain unique relevant IDs for item {item_id!r}"
                    )
                parsed_groups.append(group)
            chunk_groups = tuple(parsed_groups)
        if not answerable and chunk_groups:
            raise ValueError(
                f"Unanswerable item {item_id!r} cannot define relevant_chunk_groups"
            )

        seen_ids.add(item_id)
        items.append(
            EvaluationItem(
                id=item_id,
                question=question,
                relevant_chunk_ids=chunk_ids,
                answerable=answerable,
                category=category,
                relevant_chunk_groups=chunk_groups,
            )
        )

    return items


def hit_at_k(retrieved_ids: list[int], relevant_ids: frozenset[int], k: int) -> bool:
    return bool(set(retrieved_ids[:k]) & relevant_ids)


def reciprocal_rank(retrieved_ids: list[int], relevant_ids: frozenset[int]) -> float:
    for rank, chunk_id in enumerate(retrieved_ids, start=1):
        if chunk_id in relevant_ids:
            return 1.0 / rank
    return 0.0


def evidence_group_recall_at_k(
    retrieved_ids: list[int],
    item: EvaluationItem,
    k: int,
) -> float:
    groups = item.relevant_chunk_groups or (item.relevant_chunk_ids,)
    retrieved = set(retrieved_ids[:k])
    return sum(bool(retrieved & group) for group in groups) / len(groups)


def calculate_metrics(
    items: list[EvaluationItem],
    rankings: list[list[int]],
) -> StageMetrics:
    if not items or len(items) != len(rankings):
        raise ValueError("Dataset items and rankings must be non-empty and aligned")

    answerable_pairs = [
        (item, ranking)
        for item, ranking in zip(items, rankings)
        if item.answerable
    ]
    answerability_matches = [
        bool(ranking) == item.answerable
        for item, ranking in zip(items, rankings)
    ]
    false_positives = sum(
        bool(ranking) and not item.answerable
        for item, ranking in zip(items, rankings)
    )
    false_negatives = sum(
        not ranking and item.answerable
        for item, ranking in zip(items, rankings)
    )

    answerable_count = len(answerable_pairs)
    recall_at_5 = (
        sum(hit_at_k(ranking, item.relevant_chunk_ids, 5) for item, ranking in answerable_pairs)
        / answerable_count
        if answerable_count
        else 0.0
    )
    recall_at_10 = (
        sum(hit_at_k(ranking, item.relevant_chunk_ids, 10) for item, ranking in answerable_pairs)
        / answerable_count
        if answerable_count
        else 0.0
    )
    recall_at_20 = (
        sum(hit_at_k(ranking, item.relevant_chunk_ids, 20) for item, ranking in answerable_pairs)
        / answerable_count
        if answerable_count
        else 0.0
    )
    recall_at_30 = (
        sum(hit_at_k(ranking, item.relevant_chunk_ids, 30) for item, ranking in answerable_pairs)
        / answerable_count
        if answerable_count
        else 0.0
    )
    evidence_group_recall_at_5 = (
        sum(evidence_group_recall_at_k(ranking, item, 5) for item, ranking in answerable_pairs)
        / answerable_count
        if answerable_count
        else 0.0
    )
    evidence_group_recall_at_10 = (
        sum(evidence_group_recall_at_k(ranking, item, 10) for item, ranking in answerable_pairs)
        / answerable_count
        if answerable_count
        else 0.0
    )
    mrr = (
        sum(reciprocal_rank(ranking, item.relevant_chunk_ids) for item, ranking in answerable_pairs)
        / answerable_count
        if answerable_count
        else 0.0
    )

    return StageMetrics(
        questions=len(items),
        answerable_questions=answerable_count,
        recall_at_5=recall_at_5,
        recall_at_10=recall_at_10,
        recall_at_20=recall_at_20,
        recall_at_30=recall_at_30,
        evidence_group_recall_at_5=evidence_group_recall_at_5,
        evidence_group_recall_at_10=evidence_group_recall_at_10,
        mrr=mrr,
        answerability_accuracy=sum(answerability_matches) / len(items),
        false_positives=false_positives,
        false_negatives=false_negatives,
    )


def _chunk_id(chunk: dict[str, Any]) -> int:
    return int(chunk["chunk_id"])


def _optional_score(chunk: dict[str, Any], key: str) -> float | None:
    value = chunk.get(key)
    return round(float(value), 6) if value is not None else None


def _serialize_chunk(chunk: dict[str, Any], *, rank: int | None = None) -> dict[str, Any]:
    serialized = {
        "chunk_id": _chunk_id(chunk),
        "publication_id": int(chunk["publication_id"]),
        "chunk_index": (
            int(chunk["chunk_index"]) if chunk.get("chunk_index") is not None else None
        ),
        "publication_title": chunk.get("publication_title"),
        "similarity": _optional_score(chunk, "similarity"),
        "fts_score": _optional_score(chunk, "text_score"),
        "rrf_score": _optional_score(chunk, "rrf_score"),
        "reranker_score": _optional_score(chunk, "reranker_score"),
        "vector_rank": chunk.get("vector_rank"),
        "fts_rank": chunk.get("text_rank"),
        "text_preview": " ".join(str(chunk.get("text") or "").split())[:300],
    }
    if rank is not None:
        serialized["rank"] = rank
    return serialized


def _find_chunk(chunks: list[dict[str, Any]], chunk_id: int) -> tuple[int, dict[str, Any]] | None:
    for rank, chunk in enumerate(chunks, start=1):
        if _chunk_id(chunk) == chunk_id:
            return rank, chunk
    return None


def _expected_observation(chunks: list[dict[str, Any]], chunk_id: int) -> dict[str, Any]:
    found = _find_chunk(chunks, chunk_id)
    if found is None:
        return {
            "found": False,
            "rank": None,
            "similarity": None,
            "fts_score": None,
            "rrf_score": None,
            "reranker_score": None,
        }
    rank, chunk = found
    return {
        "found": True,
        "rank": rank,
        "similarity": _optional_score(chunk, "similarity"),
        "fts_score": _optional_score(chunk, "text_score"),
        "rrf_score": _optional_score(chunk, "rrf_score"),
        "reranker_score": _optional_score(chunk, "reranker_score"),
    }


def _best_relevant_rank(chunks: list[dict[str, Any]], relevant_ids: frozenset[int]) -> int | None:
    ranks = [
        rank
        for rank, chunk in enumerate(chunks, start=1)
        if _chunk_id(chunk) in relevant_ids
    ]
    return min(ranks) if ranks else None


def _build_rrf_impact(
    items: list[EvaluationItem],
    vector_results: list[list[dict[str, Any]]],
    hybrid_results: list[list[dict[str, Any]]],
) -> dict[str, Any]:
    by_category: dict[str, Any] = {}
    for category in RETRIEVAL_CATEGORIES:
        comparisons = []
        counts = {"improved": 0, "unchanged": 0, "worsened": 0, "gained": 0, "lost": 0}
        for item, vector_chunks, hybrid_chunks in zip(items, vector_results, hybrid_results):
            if item.category != category:
                continue
            vector_rank = _best_relevant_rank(vector_chunks, item.relevant_chunk_ids)
            hybrid_rank = _best_relevant_rank(hybrid_chunks, item.relevant_chunk_ids)
            if vector_rank is None and hybrid_rank is None:
                outcome = "unchanged"
            elif vector_rank is None:
                outcome = "gained"
            elif hybrid_rank is None:
                outcome = "lost"
            elif hybrid_rank < vector_rank:
                outcome = "improved"
            elif hybrid_rank > vector_rank:
                outcome = "worsened"
            else:
                outcome = "unchanged"
            counts[outcome] += 1
            comparisons.append(
                {
                    "id": item.id,
                    "vector_rank": vector_rank,
                    "hybrid_rank": hybrid_rank,
                    "outcome": outcome,
                }
            )
        by_category[category] = {"counts": counts, "questions": comparisons}
    return by_category


def _build_question_diagnostics(
    items: list[EvaluationItem],
    stage_results: dict[str, list[list[dict[str, Any]]]],
    reranker_scored_results: list[list[dict[str, Any]]] | None = None,
) -> list[dict[str, Any]]:
    diagnostics = []
    for index, item in enumerate(items):
        per_stage = {
            stage_name: stage_results[stage_name][index]
            for stage_name in stage_results
        }
        expected_chunks = []
        hybrid_chunks = per_stage.get("hybrid", [])
        gate_chunks = per_stage.get("relevance_gate", [])

        for expected_id in sorted(item.relevant_chunk_ids):
            stages: dict[str, dict[str, Any]] = {
                stage_name: _expected_observation(chunks, expected_id)
                for stage_name, chunks in per_stage.items()
            }
            if "reranker" in stages and reranker_scored_results is not None:
                scored_match = _find_chunk(
                    reranker_scored_results[index],
                    expected_id,
                )
                if scored_match is not None:
                    pre_filter_rank, scored_chunk = scored_match
                    stages["reranker"]["reranker_score"] = _optional_score(
                        scored_chunk,
                        "reranker_score",
                    )
                    stages["reranker"]["pre_filter_rank"] = pre_filter_rank
                    stages["reranker"]["original_score"] = _optional_score(
                        scored_chunk,
                        "reranker_original_score",
                    )
                    stages["reranker"]["intent_score"] = _optional_score(
                        scored_chunk,
                        "reranker_intent_score",
                    )
                    stages["reranker"]["entity_score"] = _optional_score(
                        scored_chunk,
                        "reranker_entity_score",
                    )
                    stages["reranker"]["entity_intent"] = scored_chunk.get(
                        "reranker_entity_intent"
                    )
                    stages["reranker"]["passed_threshold"] = bool(
                        scored_chunk.get("reranker_passed_threshold")
                    )
            hybrid_match = _find_chunk(hybrid_chunks, expected_id)
            gate_match = _find_chunk(gate_chunks, expected_id)
            if hybrid_match is None:
                gate_decision = {
                    "evaluated": False,
                    "accepted": False,
                    "mode": None,
                    "rejection_reasons": ["not_in_hybrid_candidates"],
                }
            else:
                _, hybrid_chunk = hybrid_match
                explanation = explain_source_relevance(item.question, hybrid_chunk)
                if gate_match is not None:
                    mode = (
                        "direct"
                        if explanation["directly_relevant"]
                        else "cross_language_expansion"
                        if explanation.get("cross_language_relevant")
                        else "cross_language_fallback"
                    )
                    gate_decision = {
                        "evaluated": True,
                        "accepted": True,
                        "mode": mode,
                        **explanation,
                    }
                else:
                    reasons = list(explanation["rejection_reasons"])
                    if not explanation["directly_relevant"]:
                        reasons.append("not_selected_by_cross_language_fallback")
                    gate_decision = {
                        "evaluated": True,
                        "accepted": False,
                        "mode": None,
                        **explanation,
                        "rejection_reasons": list(dict.fromkeys(reasons)),
                    }
            expected_chunks.append(
                {
                    "chunk_id": expected_id,
                    "stages": stages,
                    "relevance_gate_decision": gate_decision,
                }
            )

        diagnostics.append(
            {
                "id": item.id,
                "question": item.question,
                "category": item.category,
                "answerable": item.answerable,
                "expected_chunk_ids": sorted(item.relevant_chunk_ids),
                "expected_chunk_groups": [
                    sorted(group) for group in item.relevant_chunk_groups
                ],
                "fts_query": {
                    "terms": extract_full_text_terms(item.question),
                    "expanded_terms": extract_expanded_full_text_terms(
                        item.question
                    ),
                    "entity_terms": extract_entity_search_terms(item.question),
                    "exact_terms": extract_exact_search_terms(item.question),
                },
                "expected_chunks": expected_chunks,
                "stages": {
                    stage_name: {
                        "result_count": len(chunks),
                        "results": [
                            _serialize_chunk(chunk, rank=rank)
                            for rank, chunk in enumerate(chunks, start=1)
                        ],
                    }
                    for stage_name, chunks in per_stage.items()
                },
            }
        )
    return diagnostics


def build_report(
    *,
    dataset_path: Path,
    items: list[EvaluationItem],
    stage_results: dict[str, list[list[dict[str, Any]]]],
    candidate_limit: int,
    min_similarity: float,
    reranker_scored_results: list[list[dict[str, Any]]] | None = None,
) -> dict[str, Any]:
    stages: dict[str, Any] = {}
    for stage_name, results in stage_results.items():
        rankings = [[_chunk_id(chunk) for chunk in chunks] for chunks in results]
        overall = calculate_metrics(items, rankings)
        categories: dict[str, dict[str, int | float]] = {}

        for category in sorted({item.category for item in items}):
            indexes = [
                index for index, item in enumerate(items) if item.category == category
            ]
            category_items = [items[index] for index in indexes]
            category_rankings = [rankings[index] for index in indexes]
            categories[category] = calculate_metrics(
                category_items,
                category_rankings,
            ).as_dict()

        failures = []
        for item, chunks, ranking in zip(items, results, rankings):
            missed = item.answerable and not hit_at_k(
                ranking,
                item.relevant_chunk_ids,
                10,
            )
            incomplete_evidence = bool(
                item.answerable
                and evidence_group_recall_at_k(ranking, item, 10) < 1.0
            )
            wrong_answerability = bool(ranking) != item.answerable
            if missed or incomplete_evidence or wrong_answerability:
                failures.append(
                    {
                        "id": item.id,
                        "question": item.question,
                        "category": item.category,
                        "answerable": item.answerable,
                        "predicted_answerable": bool(ranking),
                        "expected_chunk_ids": sorted(item.relevant_chunk_ids),
                        "expected_chunk_groups": [
                            sorted(group) for group in item.relevant_chunk_groups
                        ],
                        "evidence_group_recall_at_10": evidence_group_recall_at_k(
                            ranking,
                            item,
                            10,
                        ),
                        "retrieved": [
                            _serialize_chunk(chunk, rank=rank)
                            for rank, chunk in enumerate(chunks[:10], start=1)
                        ],
                    }
                )

        stages[stage_name] = {
            "overall": overall.as_dict(),
            "by_category": categories,
            "failures": failures,
        }

    try:
        rendered_dataset_path = dataset_path.resolve().relative_to(
            Path.cwd().resolve()
        ).as_posix()
    except ValueError:
        rendered_dataset_path = str(dataset_path)

    analysis: dict[str, Any] = {}
    if "vector" in stage_results and "hybrid" in stage_results:
        analysis["rrf_impact_by_category"] = _build_rrf_impact(
            items,
            stage_results["vector"],
            stage_results["hybrid"],
        )

    ground_truth_audit = [
        {"question_id": question_id, "chunk_id": chunk_id, "reason": reason}
        for question_id, additions in GROUND_TRUTH_AUDIT.items()
        for chunk_id, reason in additions.items()
    ]
    return {
        "dataset": rendered_dataset_path,
        "questions": len(items),
        "settings": {
            "embedding_model": settings.embedding_model_name,
            "reranker_model": settings.reranker_model_name,
            "vector_limit": VECTOR_TOP_K,
            "fts_limit": FULL_TEXT_TOP_K,
            "candidate_limit": candidate_limit,
            "min_similarity": min_similarity,
        },
        "ground_truth_audit": ground_truth_audit,
        "stages": stages,
        "analysis": analysis,
        "questions_diagnostics": _build_question_diagnostics(
            items,
            stage_results,
            reranker_scored_results,
        ),
    }


async def validate_ground_truth(items: list[EvaluationItem]) -> None:
    expected_ids = set().union(*(item.relevant_chunk_ids for item in items))
    async with async_session_maker() as session:
        existing_ids = set(
            (
                await session.scalars(
                    select(DocumentChunk.id).where(DocumentChunk.id.in_(expected_ids))
                )
            ).all()
        )
    missing_ids = sorted(expected_ids - existing_ids)
    if missing_ids:
        raise ValueError(f"Ground-truth chunks are missing from the database: {missing_ids}")


async def evaluate(args: argparse.Namespace) -> dict[str, Any]:
    items = load_dataset(args.dataset)
    await validate_ground_truth(items)
    embedding_service = EmbeddingService(
        settings.embedding_model_name,
        batch_size=settings.embedding_batch_size,
        cpu_threads=settings.embedding_cpu_threads,
        max_concurrent_jobs=settings.embedding_max_concurrent_jobs,
    )
    stage_results: dict[str, list[list[dict[str, Any]]]] = {
        "vector": [],
        "fts": [],
        "hybrid": [],
        "relevance_gate": [],
    }
    if not args.skip_reranker:
        stage_results["reranker"] = []
    reranker_scored_results: list[list[dict[str, Any]]] | None = (
        [] if not args.skip_reranker else None
    )

    reranker_service = None
    async with async_session_maker() as session:
        repository = SemanticSearchRepository(session)
        for index, item in enumerate(items, start=1):
            print(
                f"[{index:02d}/{len(items):02d}] {item.id}: {item.question}",
                flush=True,
            )
            query_embedding = await asyncio.to_thread(
                embedding_service.embed_query,
                item.question,
            )
            vector_chunks = await repository.search_vector_chunks(
                query_embedding=query_embedding,
                embedding_model=embedding_service.model_name,
                limit=VECTOR_TOP_K,
                min_similarity=args.min_similarity,
            )
            fts_chunks = await repository.search_full_text_chunks(
                item.question,
                limit=FULL_TEXT_TOP_K,
            )
            hybrid_chunks = reciprocal_rank_fusion(
                vector_chunks,
                fts_chunks,
                limit=args.candidate_limit,
            )
            relevant_chunks = filter_relevant_sources(
                item.question,
                hybrid_chunks,
                limit=len(hybrid_chunks),
            )
            stage_results["vector"].append(vector_chunks)
            stage_results["fts"].append(fts_chunks)
            stage_results["hybrid"].append(hybrid_chunks)
            stage_results["relevance_gate"].append(relevant_chunks)

            if not args.skip_reranker:
                if relevant_chunks and reranker_service is None:
                    reranker_service = await asyncio.to_thread(get_reranker_service)
                reranked_chunks, scored_chunks = (
                    await asyncio.to_thread(
                        reranker_service.rerank_with_diagnostics,
                        item.question,
                        relevant_chunks,
                        limit=args.reranker_limit,
                    )
                    if reranker_service is not None
                    else ([], [])
                )
                stage_results["reranker"].append(
                    diversify_chunks_by_publication(
                        reranked_chunks,
                        args.reranker_limit,
                    )
                )
                assert reranker_scored_results is not None
                reranker_scored_results.append(scored_chunks)

    return build_report(
        dataset_path=args.dataset,
        items=items,
        stage_results=stage_results,
        candidate_limit=args.candidate_limit,
        min_similarity=args.min_similarity,
        reranker_scored_results=reranker_scored_results,
    )


def _print_metrics(metrics: dict[str, int | float]) -> None:
    print(f"Recall@5:  {metrics['Recall@5']:.3f}")
    print(f"Recall@10: {metrics['Recall@10']:.3f}")
    print(f"Recall@20: {metrics['Recall@20']:.3f}")
    print(f"Recall@30: {metrics['Recall@30']:.3f}")
    print(f"Evidence group recall@5:  {metrics['EvidenceGroupRecall@5']:.3f}")
    print(f"Evidence group recall@10: {metrics['EvidenceGroupRecall@10']:.3f}")
    print(f"MRR:       {metrics['MRR']:.3f}")
    print(f"Answerability accuracy: {metrics['answerability_accuracy']:.3f}")
    print(
        f"False positives: {metrics['false_positives']} | "
        f"False negatives: {metrics['false_negatives']}"
    )


def print_report(report: dict[str, Any], *, max_errors: int) -> None:
    print("\n=== Retrieval evaluation ===")
    print(f"Questions: {report['questions']}")
    for stage_name, stage in report["stages"].items():
        print(f"\n--- {stage_name} ---")
        _print_metrics(stage["overall"])
        print("By category:")
        for category in RETRIEVAL_CATEGORIES:
            metrics = stage["by_category"][category]
            print(
                f"  {category}: R@5={metrics['Recall@5']:.3f}, "
                f"R@10={metrics['Recall@10']:.3f}, "
                f"MRR={metrics['MRR']:.3f}"
            )

    if report["analysis"].get("rrf_impact_by_category"):
        print("\n--- RRF impact versus vector search ---")
        for category, impact in report["analysis"]["rrf_impact_by_category"].items():
            counts = impact["counts"]
            print(
                f"  {category}: improved={counts['improved']}, "
                f"unchanged={counts['unchanged']}, worsened={counts['worsened']}, "
                f"gained={counts['gained']}, lost={counts['lost']}"
            )

    final_stage_name = next(reversed(report["stages"]))
    failures = report["stages"][final_stage_name]["failures"]
    if failures:
        print(f"\nFailures at final stage ({final_stage_name}):")
        for failure in failures[:max_errors]:
            found_ids = [chunk["chunk_id"] for chunk in failure["retrieved"]]
            print(
                f"  {failure['id']} [{failure['category']}] "
                f"expected={failure['expected_chunk_ids']} found={found_ids}\n"
                f"    {failure['question']}"
            )
        if len(failures) > max_errors:
            print(f"  ... and {len(failures) - max_errors} more")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Evaluate vector, FTS, RRF, relevance gate, and reranker stages."
    )
    parser.add_argument(
        "--dataset",
        type=Path,
        required=True,
        help="Path to a retrieval evaluation dataset in JSON format.",
    )
    parser.add_argument("--candidate-limit", type=int, default=HYBRID_TOP_K)
    parser.add_argument("--reranker-limit", type=int, default=8)
    parser.add_argument("--min-similarity", type=float, default=0.55)
    parser.add_argument("--skip-reranker", action="store_true")
    parser.add_argument("--max-errors", type=int, default=20)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    if not 1 <= args.candidate_limit <= HYBRID_TOP_K:
        parser.error(f"--candidate-limit must be between 1 and {HYBRID_TOP_K}")
    if args.reranker_limit < 1:
        parser.error("--reranker-limit must be positive")
    if not 0.0 <= args.min_similarity <= 1.0:
        parser.error("--min-similarity must be between 0 and 1")
    if args.max_errors < 0:
        parser.error("--max-errors cannot be negative")
    return args


def main() -> None:
    args = parse_args()
    report = asyncio.run(evaluate(args))
    print_report(report, max_errors=args.max_errors)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            f"{json.dumps(report, ensure_ascii=False, indent=2)}\n",
            encoding="utf-8",
        )
        print(f"\nJSON report: {args.output}")


if __name__ == "__main__":
    main()
