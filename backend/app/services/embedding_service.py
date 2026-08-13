from threading import BoundedSemaphore

import numpy as np

from app.core.embedding_models import get_embedding_model_spec


class EmbeddingService:
    def __init__(
        self,
        model_name: str,
        *,
        batch_size: int = 16,
        cpu_threads: int = 2,
        max_concurrent_jobs: int = 1,
    ) -> None:
        import torch
        from sentence_transformers import SentenceTransformer

        self.model_spec = get_embedding_model_spec(model_name)
        self.model_name = self.model_spec.name
        self.batch_size = max(1, batch_size)
        self._encode_slots = BoundedSemaphore(max(1, max_concurrent_jobs))

        # PyTorch otherwise tends to occupy every available CPU core. A small,
        # explicit limit keeps PDF automation from making the whole app sluggish.
        torch.set_num_threads(max(1, cpu_threads))
        self.model = SentenceTransformer(model_name)

    @staticmethod
    def _prefix_once(text: str, prefix: str) -> str:
        if not prefix:
            return text

        # Callers may pass already prepared E5 input (for example from a CLI).
        # Canonicalizing it here guarantees exactly one role prefix.
        if text.casefold().startswith(prefix.casefold()):
            text = text[len(prefix) :]

        return f"{prefix}{text}"

    def _embedding_windows(
        self,
        text: str,
        *,
        input_prefix: str = "",
    ) -> list[str]:
        """Cover long chunks without silently truncating their final sentences."""

        tokenizer = self.model.tokenizer
        max_sequence_length = max(8, int(self.model.max_seq_length))
        special_tokens = tokenizer.num_special_tokens_to_add(pair=False)
        prefix_tokens = tokenizer.encode(
            input_prefix,
            add_special_tokens=False,
            truncation=False,
        )
        available_tokens = max(
            1,
            max_sequence_length - special_tokens - len(prefix_tokens),
        )

        if input_prefix and text.casefold().startswith(input_prefix.casefold()):
            text = text[len(input_prefix) :]

        all_token_ids = tokenizer.encode(
            text,
            add_special_tokens=False,
            truncation=False,
        )

        if len(all_token_ids) <= available_tokens:
            return [self._prefix_once(text, input_prefix)]

        prefix = ""
        body = text

        if "\n\n" in text:
            possible_prefix, possible_body = text.split("\n\n", 1)
            prefix_lines = possible_prefix.splitlines()

            if prefix_lines and all(
                line.startswith("[") and line.endswith("]")
                for line in prefix_lines
            ):
                prefix = possible_prefix
                body = possible_body

        prefix_token_ids = tokenizer.encode(
            prefix,
            add_special_tokens=False,
            truncation=False,
        )
        prefix_budget = available_tokens // 3

        if len(prefix_token_ids) > prefix_budget:
            prefix_token_ids = prefix_token_ids[:prefix_budget]

        body_token_ids = tokenizer.encode(
            body,
            add_special_tokens=False,
            truncation=False,
        )
        body_window_size = max(1, available_tokens - len(prefix_token_ids))
        overlap = min(32, max(0, body_window_size // 5))
        step = max(1, body_window_size - overlap)
        windows: list[str] = []

        for start in range(0, len(body_token_ids), step):
            body_window = body_token_ids[start : start + body_window_size]

            if not body_window:
                break

            token_ids = [*prefix_token_ids, *body_window]
            window = tokenizer.decode(
                token_ids,
                skip_special_tokens=True,
                clean_up_tokenization_spaces=True,
            )
            windows.append(self._prefix_once(window, input_prefix))

            if start + body_window_size >= len(body_token_ids):
                break

        return windows or [self._prefix_once(text, input_prefix)]

    def _embed_texts(
        self,
        texts: list[str],
        *,
        input_prefix: str,
    ) -> list[list[float]]:
        if not texts:
            return []

        windows: list[str] = []
        owners: list[int] = []

        for owner, text in enumerate(texts):
            text_windows = self._embedding_windows(
                text,
                input_prefix=input_prefix,
            )
            windows.extend(text_windows)
            owners.extend([owner] * len(text_windows))

        # SentenceTransformer is shared by all API requests. Serializing the
        # expensive encode calls prevents several requests from multiplying CPU
        # and temporary-memory usage at the same time.
        with self._encode_slots:
            window_embeddings = self.model.encode(
                windows,
                batch_size=self.batch_size,
                convert_to_numpy=True,
                normalize_embeddings=True,
                show_progress_bar=False,
            )

        window_embeddings = np.asarray(window_embeddings)

        if window_embeddings.ndim == 1:
            window_embeddings = window_embeddings.reshape(1, -1)

        if window_embeddings.shape[1] != self.model_spec.dimension:
            raise ValueError(
                f"Model {self.model_name!r} returned "
                f"{window_embeddings.shape[1]} dimensions; "
                f"expected {self.model_spec.dimension}"
            )

        embeddings = np.zeros(
            (len(texts), window_embeddings.shape[1]),
            dtype=window_embeddings.dtype,
        )
        window_counts = np.zeros(len(texts), dtype=np.int32)

        for owner, window_embedding in zip(owners, window_embeddings):
            embeddings[owner] += window_embedding
            window_counts[owner] += 1

        embeddings /= window_counts[:, np.newaxis]
        norms = np.linalg.norm(embeddings, axis=1, keepdims=True)
        embeddings /= np.maximum(norms, 1e-12)
        return embeddings.tolist()

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        """Embed corpus passages using the model's document input contract."""

        return self._embed_texts(
            texts,
            input_prefix=self.model_spec.passage_prefix,
        )

    def embed_query(self, text: str) -> list[float]:
        """Embed a search query using the model's query input contract."""

        return self._embed_texts(
            [text],
            input_prefix=self.model_spec.query_prefix,
        )[0]

    # Backward-compatible document aliases for non-retrieval callers. Search
    # code intentionally uses ``embed_query`` explicitly.
    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        return self.embed_documents(texts)

    def embed_text(self, text: str) -> list[float]:
        return self.embed_documents([text])[0]

    def count_tokens(self, text: str) -> int:
        """Count model tokens without truncating the text."""

        tokenizer = self.model.tokenizer
        token_ids = tokenizer.encode(
            text,
            add_special_tokens=False,
            truncation=False,
        )
        return len(token_ids)
