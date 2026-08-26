from __future__ import annotations

import math
from threading import BoundedSemaphore
from typing import Any

from app.services.scientific_query_expansion import (
    build_geochronology_reranker_query,
    contains_geochronology_method_evidence,
)
from app.services.source_relevance import (
    build_entity_intent_reranker_query,
    score_source_relevance,
)


DEFAULT_RERANKER_MODEL = "BAAI/bge-reranker-v2-m3"


class RerankerError(RuntimeError):
    """Raised when candidates cannot be safely reranked."""


class RerankerService:
    """Score question/passage pairs with a sequence-classification cross-encoder."""

    def __init__(
        self,
        model_name: str = DEFAULT_RERANKER_MODEL,
        *,
        batch_size: int = 4,
        max_length: int = 1024,
        min_score: float = 0.5,
        top_k: int = 8,
        cpu_threads: int = 2,
        max_concurrent_jobs: int = 1,
    ) -> None:
        if not 0.0 <= min_score <= 1.0:
            raise ValueError("min_score must be between 0 and 1")

        self.model_name = model_name
        self.batch_size = max(1, batch_size)
        self.max_length = max(8, max_length)
        self.min_score = min_score
        self.top_k = max(1, top_k)
        self._rerank_slots = BoundedSemaphore(max(1, max_concurrent_jobs))

        try:
            import torch
            from transformers import AutoModelForSequenceClassification, AutoTokenizer

            self._torch = torch
            torch.set_num_threads(max(1, cpu_threads))
            self.tokenizer = AutoTokenizer.from_pretrained(model_name)
            self.model = AutoModelForSequenceClassification.from_pretrained(model_name)
            self.model.eval()
        except Exception as exc:
            raise RerankerError(
                f"Could not load reranker {self.model_name!r}"
            ) from exc

    def _score_pairs(self, pairs: list[tuple[str, str]]) -> list[float]:
        if not pairs:
            return []

        scores: list[float] = []

        try:
            with self._rerank_slots, self._torch.inference_mode():
                for start in range(0, len(pairs), self.batch_size):
                    batch = pairs[start : start + self.batch_size]
                    questions = [question for question, _passage in batch]
                    passages = [passage for _question, passage in batch]
                    inputs = self.tokenizer(
                        questions,
                        passages,
                        padding=True,
                        truncation=True,
                        max_length=self.max_length,
                        return_tensors="pt",
                    )
                    logits = self.model(**inputs, return_dict=True).logits
                    batch_scores = self._torch.sigmoid(logits.reshape(-1).float())
                    scores.extend(float(score) for score in batch_scores.tolist())
        except Exception as exc:
            raise RerankerError(
                f"Reranker {self.model_name!r} failed to score candidates"
            ) from exc

        if len(scores) != len(pairs) or any(not math.isfinite(score) for score in scores):
            raise RerankerError(
                f"Reranker {self.model_name!r} returned invalid scores"
            )

        return scores

    def rerank(
        self,
        question: str,
        chunks: list[dict[str, Any]],
        *,
        limit: int | None = None,
    ) -> list[dict[str, Any]]:
        """Return only candidates above the relevance threshold, best first."""

        ranked, _scored = self.rerank_with_diagnostics(
            question,
            chunks,
            limit=limit,
        )
        return ranked

    def rerank_with_diagnostics(
        self,
        question: str,
        chunks: list[dict[str, Any]],
        *,
        limit: int | None = None,
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        """Return production results plus scores for every input candidate.

        The first element is exactly what ``rerank`` returns. The second is
        diagnostic-only and retains below-threshold candidates so evaluation
        can explain why an expected chunk disappeared.
        """

        if not chunks:
            return [], []

        passages = [str(chunk.get("text") or "").strip() for chunk in chunks]
        original_scores = self._score_pairs(
            [(question, passage) for passage in passages]
        )
        intent_query = build_geochronology_reranker_query(question)
        intent_indices = [
            index
            for index, passage in enumerate(passages)
            if intent_query
            and passage
            and contains_geochronology_method_evidence(passage)
        ]
        intent_scores_by_index: dict[int, float] = {}
        if intent_query and intent_indices:
            intent_scores = self._score_pairs(
                [(intent_query, passages[index]) for index in intent_indices]
            )
            intent_scores_by_index = dict(zip(intent_indices, intent_scores))

        entity_intent = build_entity_intent_reranker_query(question)
        entity_query = entity_intent[0] if entity_intent else None
        entity_intent_kind = entity_intent[1] if entity_intent else None
        entity_indices: list[int] = []
        entity_exact_matches_by_index: dict[int, bool] = {}
        if entity_query:
            for index, (chunk, passage) in enumerate(zip(chunks, passages)):
                if not passage:
                    continue
                relevance = score_source_relevance(question, chunk)
                exact_match = bool(relevance.matched_specific_tokens)
                if exact_match:
                    entity_indices.append(index)
                    entity_exact_matches_by_index[index] = True

        entity_scores_by_index: dict[int, float] = {}
        if entity_query and entity_indices:
            entity_scores = self._score_pairs(
                [(entity_query, passages[index]) for index in entity_indices]
            )
            entity_scores_by_index = dict(zip(entity_indices, entity_scores))

        scores = [
            max(
                original_score,
                intent_scores_by_index.get(index, 0.0),
                entity_scores_by_index.get(index, 0.0),
            )
            for index, original_score in enumerate(original_scores)
        ]
        scored = [
            {
                **chunk,
                "reranker_score": score,
                "reranker_original_score": original_score,
                "reranker_intent_score": intent_scores_by_index.get(index),
                "reranker_entity_score": entity_scores_by_index.get(index),
                "reranker_entity_intent": entity_intent_kind,
                "reranker_entity_exact_match": entity_exact_matches_by_index.get(
                    index,
                    False,
                ),
                "reranker_passed_threshold": bool(
                    passage
                    and (
                        score >= self.min_score
                        or (
                            entity_intent_kind == "source_lookup"
                            and entity_exact_matches_by_index.get(index, False)
                        )
                    )
                ),
            }
            for index, (chunk, passage, score, original_score) in enumerate(
                zip(chunks, passages, scores, original_scores)
            )
        ]
        scored.sort(
            key=lambda chunk: (
                -float(chunk["reranker_score"]),
                -float(chunk.get("rrf_score") or 0.0),
                -float(chunk.get("similarity") or 0.0),
                int(chunk.get("chunk_id") or 0),
            )
        )
        effective_limit = min(max(1, limit or self.top_k), self.top_k)
        ranked = [
            {
                key: value
                for key, value in chunk.items()
                if key not in {
                    "reranker_passed_threshold",
                    "reranker_original_score",
                    "reranker_intent_score",
                    "reranker_entity_score",
                    "reranker_entity_intent",
                    "reranker_entity_exact_match",
                }
            }
            for chunk in scored
            if chunk["reranker_passed_threshold"]
        ][:effective_limit]
        return ranked, scored
