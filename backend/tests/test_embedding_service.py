from threading import BoundedSemaphore

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
