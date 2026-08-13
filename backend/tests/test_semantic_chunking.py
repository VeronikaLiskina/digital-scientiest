import re

import pytest

from app.services.pdf_processing import build_chunk_text
from app.services.embedding_service import EmbeddingService
from app.services.semantic_chunking import (
    MAX_CHUNK_TOKENS,
    MIN_CHUNK_TOKENS,
    SemanticSource,
    estimate_token_count,
    split_sources_into_semantic_chunks,
    split_text_into_semantic_chunks,
)


class FakeEmbeddingService:
    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [[1.0, 0.0] for _ in texts]

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        return [[1.0, 0.0] for _ in texts]


def _sentence(index: int) -> str:
    return (
        f"Sentence {index:03d} explains mineral composition and laboratory "
        "measurements in sufficient detail."
    )


def _sentence_ids(text: str) -> list[int]:
    return [int(value) for value in re.findall(r"Sentence (\d{3})", text)]


@pytest.mark.asyncio
async def test_semantic_chunks_use_token_limits_and_sentence_overlap():
    text = " ".join(_sentence(index) for index in range(140))

    chunks = await split_text_into_semantic_chunks(text, FakeEmbeddingService())

    assert len(chunks) >= 3
    assert all(
        MIN_CHUNK_TOKENS <= estimate_token_count(chunk) <= MAX_CHUNK_TOKENS
        for chunk in chunks
    )

    for current, following in zip(chunks, chunks[1:]):
        current_ids = _sentence_ids(current)
        following_ids = _sentence_ids(following)
        overlap_ids = sorted(set(current_ids) & set(following_ids))
        overlap_text = " ".join(_sentence(index) for index in overlap_ids)

        assert current_ids[-len(overlap_ids):] == overlap_ids
        assert following_ids[:len(overlap_ids)] == overlap_ids
        assert 50 <= estimate_token_count(overlap_text) <= 100


@pytest.mark.asyncio
async def test_semantic_chunks_keep_page_ranges_across_one_section():
    sources = [
        SemanticSource(
            text=" ".join(_sentence(index) for index in range(35)),
            page_number=12,
        ),
        SemanticSource(
            text=" ".join(_sentence(index) for index in range(35, 75)),
            page_number=13,
        ),
    ]

    chunks = await split_sources_into_semantic_chunks(
        sources,
        FakeEmbeddingService(),
    )

    assert chunks
    assert any(chunk.page_start == 12 and chunk.page_end == 13 for chunk in chunks)
    assert all(chunk.text.endswith("detail.") for chunk in chunks)


def test_chunk_context_contains_publication_section_and_page_range():
    chunk = build_chunk_text(
        publication_title="Carbonatite study",
        section_title="Chemical composition",
        page_number=12,
        end_page_number=13,
        chunk_text="The Fe2O3 content was 14.7%.",
    )

    assert "[publication: Carbonatite study]" in chunk
    assert "[section: Chemical composition]" in chunk
    assert "[pages: 12–13]" in chunk
    assert chunk.endswith("The Fe2O3 content was 14.7%.")


def test_embedding_windows_cover_long_chunk_and_repeat_context():
    class CharacterTokenizer:
        @staticmethod
        def encode(text, **_kwargs):
            return [ord(character) for character in text]

        @staticmethod
        def decode(token_ids, **_kwargs):
            return "".join(chr(token_id) for token_id in token_ids)

        @staticmethod
        def num_special_tokens_to_add(**_kwargs):
            return 0

    service = EmbeddingService.__new__(EmbeddingService)
    service.model = type(
        "FakeModel",
        (),
        {
            "tokenizer": CharacterTokenizer(),
            "max_seq_length": 80,
        },
    )()
    text = (
        "[publication: Study]\n[section: Results]\n[pages: 1–2]\n\n"
        + "A" * 150
        + "THE_END"
    )

    windows = service._embedding_windows(text)

    assert len(windows) > 1
    assert all(window.startswith("[publication:") for window in windows)
    assert "THE_END" in windows[-1]
