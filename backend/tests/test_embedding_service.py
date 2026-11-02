from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
from threading import BoundedSemaphore, Event, Lock

import numpy as np
import pytest

from app.core.embedding_models import E5_MODEL_NAME, LEGACY_MPNET_MODEL_NAME
from app.core.embedding_models import get_embedding_model_spec
from app.services.embedding_service import EmbeddingService


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


class CapturingModel:
    tokenizer = CharacterTokenizer()
    max_seq_length = 512

    def __init__(self):
        self.encoded_texts: list[str] = []

    def encode(self, texts, **_kwargs):
        self.encoded_texts.extend(texts)
        vectors = np.zeros((len(texts), 768), dtype=np.float32)
        vectors[:, 0] = 3.0
        vectors[:, 1] = 4.0
        return vectors


def make_service(model_name: str) -> EmbeddingService:
    service = EmbeddingService.__new__(EmbeddingService)
    service.model_spec = get_embedding_model_spec(model_name)
    service.model_name = model_name
    service.batch_size = 8
    service._encode_slots = BoundedSemaphore(1)
    service._query_cache = OrderedDict()
    service._query_cache_lock = Lock()
    service._query_inflight = {}
    service.model = CapturingModel()
    return service


def test_e5_uses_distinct_query_and_passage_prefixes_exactly_once():
    service = make_service(E5_MODEL_NAME)

    query_embedding = service.embed_query("query: где находится массив?")
    document_embeddings = service.embed_documents(
        ["Описание массива", "passage: Геохимические результаты"]
    )

    assert service.model.encoded_texts == [
        "query: где находится массив?",
        "passage: Описание массива",
        "passage: Геохимические результаты",
    ]
    assert np.linalg.norm(query_embedding) == pytest.approx(1.0)
    assert all(
        np.linalg.norm(embedding) == pytest.approx(1.0)
        for embedding in document_embeddings
    )


def test_legacy_model_remains_available_without_e5_prefixes():
    service = make_service(LEGACY_MPNET_MODEL_NAME)

    service.embed_query("Вопрос")
    service.embed_documents(["Документ"])

    assert service.model.encoded_texts == ["Вопрос", "Документ"]


def test_unsupported_embedding_model_is_rejected():
    with pytest.raises(ValueError, match="Unsupported embedding model"):
        get_embedding_model_spec("unknown/model")


def test_repeated_query_reuses_embedding_without_changing_passage_encoding():
    service = make_service(E5_MODEL_NAME)
    first = service.embed_query("Baikal rift")
    second = service.embed_query("Baikal rift")
    service.embed_documents(["Baikal rift"])

    assert second == first
    assert service.model.encoded_texts == ["query: Baikal rift", "passage: Baikal rift"]


def test_mutating_query_embedding_does_not_change_cached_vector():
    service = make_service(E5_MODEL_NAME)
    original = service.embed_query("Baikal rift")
    expected = original.copy()
    original[0] = -99

    assert service.embed_query("Baikal rift") == expected
    assert len(service.model.encoded_texts) == 1


def test_query_cache_is_bounded_and_keeps_recent_queries():
    service = make_service(E5_MODEL_NAME)
    for number in range(256):
        service.embed_query(f"query {number}")
    service.embed_query("query 0")  # Refresh the oldest entry.
    service.embed_query("query 256")
    service.embed_query("query 0")
    service.embed_query("query 1")  # This entry should have been evicted.

    assert len(service.model.encoded_texts) == 258


def test_cached_query_does_not_wait_for_unrelated_model_calculation():
    service = make_service(E5_MODEL_NAME)
    expected = service.embed_query("cached")
    entered, release = Event(), Event()
    original_encode = service.model.encode

    def slow_encode(texts, **kwargs):
        entered.set()
        assert release.wait(5)
        return original_encode(texts, **kwargs)

    service.model.encode = slow_encode
    with ThreadPoolExecutor(max_workers=2) as pool:
        slow = pool.submit(service.embed_query, "new question")
        try:
            assert entered.wait(1)
            cached = pool.submit(service.embed_query, "cached")
            assert cached.result(timeout=0.5) == expected
        finally:
            release.set()
        slow.result(timeout=2)


def test_simultaneous_identical_queries_share_one_computation():
    service = make_service(E5_MODEL_NAME)
    entered, release = Event(), Event()
    original_encode = service.model.encode

    def slow_encode(texts, **kwargs):
        entered.set()
        assert release.wait(5)
        return original_encode(texts, **kwargs)

    service.model.encode = slow_encode
    with ThreadPoolExecutor(max_workers=4) as pool:
        first = pool.submit(service.embed_query, "same question")
        try:
            assert entered.wait(1)
            others = [pool.submit(service.embed_query, "same question") for _ in range(3)]
        finally:
            release.set()
        expected = first.result(timeout=2)
        assert all(future.result(timeout=2) == expected for future in others)
    assert service.model.encoded_texts == ["query: same question"]


def test_failed_query_embedding_can_be_retried():
    service = make_service(E5_MODEL_NAME)
    original_encode = service.model.encode

    def fail(*_args, **_kwargs):
        raise RuntimeError("temporary encoding error")

    service.model.encode = fail
    with pytest.raises(RuntimeError, match="temporary encoding error"):
        service.embed_query("retry question")
    service.model.encode = original_encode
    assert np.linalg.norm(service.embed_query("retry question")) == pytest.approx(1.0)
    assert not service._query_inflight
