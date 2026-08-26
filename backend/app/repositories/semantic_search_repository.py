import logging
import re
from typing import Any

from sqlalchemy import and_, case, func, literal, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.document_chunk import DocumentChunk
from app.models.publication import Publication
from app.services.scientific_query_expansion import (
    GEOCHRONOLOGY_FTS_MARKERS,
    expand_scientific_query_terms,
    extract_geochronology_aspect_terms,
    extract_scientific_entity_terms,
    is_geochronology_method_query,
)


logger = logging.getLogger(__name__)

# Candidate generation deliberately has higher recall than the final answer
# context. The relevance gate and reranker reduce this pool later.
VECTOR_TOP_K = 50
FULL_TEXT_TOP_K = 50
HYBRID_TOP_K = 30
RRF_K = 60
MIN_CANDIDATES_PER_RETRIEVER = 15

FULL_TEXT_TOKEN_RE = re.compile(r"[A-Za-zА-Яа-яЁё0-9]{2,}")
CHEMICAL_FORMULA_RE = re.compile(r"\b(?:[A-Z][a-z]?\d*){2,}\b")
DECIMAL_RE = re.compile(r"\b\d+[.,]\d+\b")
DOI_RE = re.compile(r"\b10\.\d{4,9}/[-._;()/:A-Z0-9]+", re.IGNORECASE)
STANDARD_RE = re.compile(r"\bГОСТ\s+\d+(?:-\d+)+\b", re.IGNORECASE)
FULL_TEXT_STOPWORDS = {
    "а",
    "без",
    "был",
    "быть",
    "в",
    "во",
    "для",
    "до",
    "его",
    "ее",
    "и",
    "из",
    "или",
    "их",
    "как",
    "какие",
    "какой",
    "каково",
    "к",
    "ко",
    "на",
    "не",
    "о",
    "об",
    "от",
    "по",
    "при",
    "про",
    "с",
    "со",
    "у",
    "это",
    "что",
    "такой",
    "такое",
    "где",
    "когда",
    "почему",
    "упоминаться",
    "упоминается",
    "упоминать",
    "упомянуть",
    "использовать",
    "использовали",
    "использовались",
    "предел",
    "пределах",
    "the",
    "a",
    "an",
    "and",
    "are",
    "for",
    "from",
    "in",
    "is",
    "of",
    "on",
    "or",
    "to",
    "what",
    "which",
    "where",
    "with",
}


def _deduplicated_terms(values: list[str]) -> list[str]:
    return list(dict.fromkeys(value.casefold() for value in values if value.strip()))


def extract_full_text_terms(query_text: str) -> list[str]:
    return _deduplicated_terms(
        [
            token
            for token in FULL_TEXT_TOKEN_RE.findall(query_text)
            if token.casefold() not in FULL_TEXT_STOPWORDS
        ]
    )


def extract_expanded_full_text_terms(query_text: str) -> list[str]:
    return expand_scientific_query_terms(
        query_text,
        original_terms=extract_full_text_terms(query_text),
        stopwords=FULL_TEXT_STOPWORDS,
    )


def extract_entity_search_terms(query_text: str) -> list[str]:
    return extract_scientific_entity_terms(
        query_text,
        stopwords=FULL_TEXT_STOPWORDS,
    )


def extract_exact_search_terms(query_text: str) -> list[str]:
    matches: list[str] = []
    for pattern in (DOI_RE, STANDARD_RE, CHEMICAL_FORMULA_RE, DECIMAL_RE):
        for match in pattern.finditer(query_text):
            value = match.group(0)
            # DOI and MIS are acronyms, not chemical formulae. Properly cased
            # formulae such as NaCl and formulae with digits remain searchable.
            if (
                pattern is CHEMICAL_FORMULA_RE
                and value.isalpha()
                and value.isupper()
            ):
                continue
            matches.append(value)
    return _deduplicated_terms(matches)


def reciprocal_rank_fusion(
    vector_results: list[dict[str, Any]],
    full_text_results: list[dict[str, Any]],
    *,
    limit: int = HYBRID_TOP_K,
    rrf_k: int = RRF_K,
    min_candidates_per_retriever: int = MIN_CANDIDATES_PER_RETRIEVER,
) -> list[dict[str, Any]]:
    """Fuse two rankings while retaining each retriever's strongest hits.

    Pure RRF can crowd a strong vector-only (notably cross-language) result
    out of the candidate pool when many weaker chunks occur in both rankings.
    The small per-retriever reserve affects candidate inclusion only; the
    retained candidates keep their ordinary RRF ordering for the reranker.
    """

    fused: dict[int, dict[str, Any]] = {}

    for result_name, results in (
        ("vector_rank", vector_results),
        ("text_rank", full_text_results),
    ):
        seen_chunk_ids: set[int] = set()
        for rank, result in enumerate(results, start=1):
            chunk_id = int(result["chunk_id"])
            if chunk_id in seen_chunk_ids:
                continue
            seen_chunk_ids.add(chunk_id)

            existing = fused.get(chunk_id)
            if existing is None:
                existing = dict(result)
                existing.update(
                    {
                        "vector_rank": None,
                        "text_rank": None,
                        "rrf_score": 0.0,
                    }
                )
                fused[chunk_id] = existing
            else:
                for key, value in result.items():
                    if existing.get(key) is None and value is not None:
                        existing[key] = value

            existing[result_name] = rank
            existing["rrf_score"] += 1.0 / (rrf_k + rank)

    def sort_key(item: dict[str, Any]) -> tuple[float, int, int, int]:
        return (
            -float(item["rrf_score"]),
            item["vector_rank"] if item["vector_rank"] is not None else 10**9,
            item["text_rank"] if item["text_rank"] is not None else 10**9,
            int(item["chunk_id"]),
        )
    ranked = sorted(
        fused.values(),
        key=sort_key,
    )
    effective_limit = max(0, limit)
    selected = ranked[:effective_limit]
    if not selected or min_candidates_per_retriever <= 0:
        return selected

    reserve = min(min_candidates_per_retriever, effective_limit // 2)
    protected_ids = {
        int(result["chunk_id"])
        for results in (vector_results, full_text_results)
        for result in results[:reserve]
    }
    selected_ids = {int(result["chunk_id"]) for result in selected}
    missing_protected = [
        result
        for result in ranked
        if int(result["chunk_id"]) in protected_ids
        and int(result["chunk_id"]) not in selected_ids
    ]

    for protected_result in missing_protected:
        replace_index = next(
            (
                index
                for index in range(len(selected) - 1, -1, -1)
                if int(selected[index]["chunk_id"]) not in protected_ids
            ),
            None,
        )
        if replace_index is None:
            break
        selected_ids.discard(int(selected[replace_index]["chunk_id"]))
        selected[replace_index] = protected_result
        selected_ids.add(int(protected_result["chunk_id"]))

    selected.sort(key=sort_key)
    return selected


def _log_results(name: str, results: list[dict[str, Any]]) -> None:
    logger.info(
        "%s=%s",
        name,
        [
            {
                "chunk_id": result.get("chunk_id"),
                "similarity": result.get("similarity"),
                "text_score": result.get("text_score"),
                "rrf_score": result.get("rrf_score"),
            }
            for result in results
        ],
    )


class SemanticSearchRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def search_vector_chunks(
        self,
        query_embedding: list[float],
        embedding_model: str,
        *,
        limit: int = VECTOR_TOP_K,
        min_similarity: float = 0.55,
    ) -> list[dict[str, Any]]:
        distance = DocumentChunk.embedding.cosine_distance(query_embedding)
        # Read a wider index window because the similarity threshold is applied
        # after pgvector has ranked the rows.
        search_limit = min(max(limit * 3, 100), 300)
        stmt = (
            select(
                DocumentChunk.id.label("chunk_id"),
                DocumentChunk.publication_id.label("publication_id"),
                DocumentChunk.chunk_index.label("chunk_index"),
                DocumentChunk.chunk_text.label("text"),
                Publication.title.label("publication_title"),
                distance.label("distance"),
            )
            .join(Publication, Publication.id == DocumentChunk.publication_id)
            .where(DocumentChunk.embedding.is_not(None))
            .where(DocumentChunk.embedding_model == embedding_model)
            .order_by(distance)
            .limit(search_limit)
        )
        result = await self.session.execute(stmt)
        vector_results: list[dict[str, Any]] = []
        for row in result.mappings().all():
            row_distance = float(row["distance"])
            similarity = 1.0 - row_distance
            if similarity < min_similarity:
                continue
            vector_results.append(
                {
                    "chunk_id": row["chunk_id"],
                    "publication_id": row["publication_id"],
                    "chunk_index": row["chunk_index"],
                    "text": row["text"],
                    "publication_title": row["publication_title"],
                    "distance": row_distance,
                    "similarity": similarity,
                }
            )
            if len(vector_results) >= limit:
                break
        return vector_results

    async def search_full_text_chunks(
        self,
        query_text: str,
        *,
        limit: int = FULL_TEXT_TOP_K,
    ) -> list[dict[str, Any]]:
        terms = extract_expanded_full_text_terms(query_text)
        entity_terms = extract_entity_search_terms(query_text)
        exact_terms = extract_exact_search_terms(query_text)
        if not terms and not entity_terms and not exact_terms:
            return []

        russian_query = func.websearch_to_tsquery("russian", query_text)
        simple_query = func.websearch_to_tsquery("simple", query_text)
        natural_query = russian_query.op("||")(simple_query)
        match_conditions = [DocumentChunk.search_vector.op("@@")(natural_query)]
        rank_expression = func.ts_rank_cd(
            DocumentChunk.search_vector,
            natural_query,
            32,
        )

        if terms:
            any_term_query = func.to_tsquery("simple", " | ".join(terms))
            match_conditions.append(
                DocumentChunk.search_vector.op("@@")(any_term_query)
            )
            rank_expression = rank_expression + (
                func.ts_rank_cd(DocumentChunk.search_vector, any_term_query, 32) * 0.25
            )

        exact_score = literal(0.0)
        for term in entity_terms:
            entity_match = func.strpos(
                func.lower(DocumentChunk.chunk_text),
                term,
            ) > 0
            match_conditions.append(entity_match)
            exact_score = exact_score + case((entity_match, 0.5), else_=0.0)

        for term in exact_terms:
            exact_match = func.strpos(
                func.lower(DocumentChunk.chunk_text),
                term,
            ) > 0
            match_conditions.append(exact_match)
            exact_score = exact_score + case((exact_match, 1.0), else_=0.0)

        # A method token alone (for example, 40Ar/39Ar) is common in this
        # corpus, as is an aspect token such as "ore". Their co-occurrence is
        # much stronger answer-bearing evidence for a composite dating-method
        # question, so keep that branch near the top of the FTS candidate list.
        aspect_terms = extract_geochronology_aspect_terms(query_text)
        if is_geochronology_method_query(query_text) and aspect_terms:
            method_match = or_(
                *(
                    func.strpos(func.lower(DocumentChunk.chunk_text), term) > 0
                    for term in GEOCHRONOLOGY_FTS_MARKERS
                )
            )
            aspect_match = or_(
                *(
                    func.strpos(func.lower(DocumentChunk.chunk_text), term) > 0
                    for term in aspect_terms
                )
            )
            exact_score = exact_score + case(
                (and_(method_match, aspect_match), 1.0),
                else_=0.0,
            )

        text_score = (rank_expression + exact_score).label("text_score")
        stmt = (
            select(
                DocumentChunk.id.label("chunk_id"),
                DocumentChunk.publication_id.label("publication_id"),
                DocumentChunk.chunk_index.label("chunk_index"),
                DocumentChunk.chunk_text.label("text"),
                Publication.title.label("publication_title"),
                text_score,
            )
            .join(Publication, Publication.id == DocumentChunk.publication_id)
            .where(or_(*match_conditions))
            .order_by(text_score.desc(), DocumentChunk.id)
            .limit(limit)
        )
        result = await self.session.execute(stmt)
        return [
            {
                "chunk_id": row["chunk_id"],
                "publication_id": row["publication_id"],
                "chunk_index": row["chunk_index"],
                "text": row["text"],
                "publication_title": row["publication_title"],
                "text_score": float(row["text_score"]),
                # FTS-only candidates have no cosine score. The downstream
                # relevance filter can still accept them by exact token coverage.
                "similarity": 0.0,
            }
            for row in result.mappings().all()
        ]

    async def search_chunks(
        self,
        query_embedding: list[float],
        embedding_model: str,
        query_text: str | None = None,
        limit: int = HYBRID_TOP_K,
        min_similarity: float = 0.55,
        max_chunks_per_publication: int | None = None,
    ) -> list[dict[str, Any]]:
        vector_results = await self.search_vector_chunks(
            query_embedding,
            embedding_model,
            limit=VECTOR_TOP_K,
            min_similarity=min_similarity,
        )
        full_text_results = (
            await self.search_full_text_chunks(query_text, limit=FULL_TEXT_TOP_K)
            if query_text
            else []
        )
        rrf_results = reciprocal_rank_fusion(
            vector_results,
            full_text_results,
            limit=min(limit, HYBRID_TOP_K),
        )

        if max_chunks_per_publication is not None:
            per_publication: dict[int, int] = {}
            capped_results: list[dict[str, Any]] = []
            for result in rrf_results:
                publication_id = int(result["publication_id"])
                count = per_publication.get(publication_id, 0)
                if count >= max_chunks_per_publication:
                    continue
                capped_results.append(result)
                per_publication[publication_id] = count + 1
            rrf_results = capped_results

        _log_results("vector_results", vector_results)
        _log_results("full_text_results", full_text_results)
        _log_results("rrf_results", rrf_results)
        return rrf_results
