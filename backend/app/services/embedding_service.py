from threading import BoundedSemaphore


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

        self.model_name = model_name
        self.batch_size = max(1, batch_size)
        self._encode_slots = BoundedSemaphore(max(1, max_concurrent_jobs))

        # PyTorch otherwise tends to occupy every available CPU core. A small,
        # explicit limit keeps PDF automation from making the whole app sluggish.
        torch.set_num_threads(max(1, cpu_threads))
        self.model = SentenceTransformer(model_name)

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []

        # SentenceTransformer is shared by all API requests. Serializing the
        # expensive encode calls prevents several requests from multiplying CPU
        # and temporary-memory usage at the same time.
        with self._encode_slots:
            embeddings = self.model.encode(
                texts,
                batch_size=self.batch_size,
                convert_to_numpy=True,
                normalize_embeddings=True,
                show_progress_bar=False,
            )

        # ``tolist`` already converts NumPy scalars to Python floats. Avoiding an
        # intermediate float64 copy cuts peak memory during large PDF imports.
        return embeddings.tolist()

    def embed_text(self, text: str) -> list[float]:
        return self.embed_texts([text])[0]
