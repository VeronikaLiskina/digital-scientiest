from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

from app.core.config import settings
from app.core.embedding_models import SUPPORTED_EMBEDDING_MODELS
from app.services.embedding_service import EmbeddingService


DEFAULT_DATASET = Path(__file__).with_name("embedding_retrieval.json")


@dataclass(frozen=True, slots=True)
class RetrievalMetrics:
    recall_at_5: float
    recall_at_10: float
    mrr: float

    def as_dict(self) -> dict[str, float]:
        return {
            "Recall@5": self.recall_at_5,
            "Recall@10": self.recall_at_10,
            "MRR": self.mrr,
        }


def calculate_metrics(
    rankings: list[list[str]],
    relevant_chunk_ids: list[set[str]],
) -> RetrievalMetrics:
    if not rankings or len(rankings) != len(relevant_chunk_ids):
        raise ValueError("Rankings and relevance judgments must be non-empty and aligned")

    recalls_at_5: list[float] = []
    recalls_at_10: list[float] = []
    reciprocal_ranks: list[float] = []

    for ranked_ids, relevant_ids in zip(rankings, relevant_chunk_ids):
        if not relevant_ids:
            raise ValueError("Every benchmark question must have a relevant chunk")

        recalls_at_5.append(len(set(ranked_ids[:5]) & relevant_ids) / len(relevant_ids))
        recalls_at_10.append(
            len(set(ranked_ids[:10]) & relevant_ids) / len(relevant_ids)
        )
        first_relevant_rank = next(
            (
                rank
                for rank, chunk_id in enumerate(ranked_ids, start=1)
                if chunk_id in relevant_ids
            ),
            None,
        )
        reciprocal_ranks.append(
            0.0 if first_relevant_rank is None else 1.0 / first_relevant_rank
        )

    return RetrievalMetrics(
        recall_at_5=float(np.mean(recalls_at_5)),
        recall_at_10=float(np.mean(recalls_at_10)),
        mrr=float(np.mean(reciprocal_ranks)),
    )


def load_dataset(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as dataset_file:
        dataset = json.load(dataset_file)

    chunk_ids = [chunk["id"] for chunk in dataset.get("chunks", [])]
    if not chunk_ids or len(chunk_ids) != len(set(chunk_ids)):
        raise ValueError("Dataset chunk IDs must be present and unique")

    known_chunk_ids = set(chunk_ids)
    for question in dataset.get("questions", []):
        relevant_ids = set(question.get("relevant_chunk_ids", []))
        if not relevant_ids or not relevant_ids <= known_chunk_ids:
            raise ValueError(
                f"Invalid relevance judgments for question {question.get('id')!r}"
            )

    return dataset


def evaluate_model(model_name: str, dataset: dict[str, Any]) -> RetrievalMetrics:
    service = EmbeddingService(
        model_name,
        batch_size=settings.embedding_batch_size,
        cpu_threads=settings.embedding_cpu_threads,
        max_concurrent_jobs=settings.embedding_max_concurrent_jobs,
    )
    chunks = dataset["chunks"]
    questions = dataset["questions"]
    chunk_ids = [chunk["id"] for chunk in chunks]

    document_embeddings = np.asarray(
        service.embed_documents([chunk["text"] for chunk in chunks]),
        dtype=np.float32,
    )
    rankings: list[list[str]] = []
    relevant_ids: list[set[str]] = []

    for question in questions:
        query_embedding = np.asarray(
            service.embed_query(question["text"]),
            dtype=np.float32,
        )
        scores = document_embeddings @ query_embedding
        order = np.argsort(-scores, kind="stable")
        rankings.append([chunk_ids[index] for index in order])
        relevant_ids.append(set(question["relevant_chunk_ids"]))

    return calculate_metrics(rankings, relevant_ids)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Compare supported embedding models on the curated retrieval set."
    )
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    parser.add_argument(
        "--models",
        nargs="+",
        choices=tuple(SUPPORTED_EMBEDDING_MODELS),
        default=[
            settings.embedding_legacy_model_name,
            settings.embedding_model_name,
        ],
    )
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    dataset = load_dataset(args.dataset)
    results = {
        model_name: evaluate_model(model_name, dataset).as_dict()
        for model_name in args.models
    }
    report = {
        "dataset": str(args.dataset),
        "questions": len(dataset["questions"]),
        "chunks": len(dataset["chunks"]),
        "models": results,
    }
    rendered = json.dumps(report, ensure_ascii=False, indent=2)
    print(rendered)

    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(f"{rendered}\n", encoding="utf-8")


if __name__ == "__main__":
    main()
