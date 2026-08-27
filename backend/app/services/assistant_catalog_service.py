from __future__ import annotations

import re
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.services.assistant_answer_service import single_answer_block
from app.services.publication_query_service import (
    DESCRIPTION_UNAVAILABLE,
    build_described_publication_catalog_answer,
    build_publication_catalog_answer,
    build_publication_count_answer,
    count_publications,
    get_publication_catalog,
    get_representative_descriptions,
    is_publication_catalog_question,
    is_publication_catalog_with_descriptions_question,
    is_publication_count_question,
)


async def answer_database_question(
    *,
    question: str,
    db: AsyncSession,
    conversation: str | None,
) -> dict[str, Any] | None:
    """Answer catalog/count questions without invoking retrieval or an LLM."""

    with_descriptions = is_publication_catalog_with_descriptions_question(
        question,
        conversation,
    )
    if with_descriptions or is_publication_catalog_question(question):
        total, publications = await get_publication_catalog(db)
        descriptions = (
            await get_representative_descriptions(
                db,
                [publication.id for publication in publications],
            )
            if with_descriptions
            else {}
        )
        answer = (
            build_described_publication_catalog_answer(total, len(publications))
            if with_descriptions
            else build_publication_catalog_answer(total, len(publications))
        )
        catalog = {
            "total": total,
            "returned_count": len(publications),
            "truncated": len(publications) < total,
            "items": [
                {
                    "publication_id": publication.id,
                    "title": publication.title,
                    "year": publication.year,
                    "authors": [
                        _format_author_name(author.full_name)
                        for author in publication.authors
                    ],
                    "publication_type": publication.publication_type,
                    "publication_url": f"/publications/{publication.id}",
                    "description": (
                        descriptions.get(publication.id, DESCRIPTION_UNAVAILABLE)
                        if with_descriptions
                        else None
                    ),
                }
                for publication in publications
            ],
        }
        return _internal_answer(
            question=question,
            answer=answer,
            answer_origin="catalog",
            catalog=catalog,
        )

    if is_publication_count_question(question):
        answer = build_publication_count_answer(await count_publications(db))
        return _internal_answer(
            question=question,
            answer=answer,
            answer_origin="internal",
            catalog=None,
        )

    return None


def _format_author_name(full_name: str) -> str:
    return re.sub(r"(?<=\.)\s+(?=[А-ЯЁA-Z]\.)", "", full_name.strip())


def _internal_answer(
    *,
    question: str,
    answer: str,
    answer_origin: str,
    catalog: dict[str, Any] | None,
) -> dict[str, Any]:
    return {
        "question": question,
        "answer": answer,
        "sources": [],
        "answer_blocks": single_answer_block(answer),
        "answer_origin": answer_origin,
        "catalog": catalog,
    }
