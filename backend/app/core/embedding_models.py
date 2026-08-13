from dataclasses import dataclass


E5_MODEL_NAME = "intfloat/multilingual-e5-base"
LEGACY_MPNET_MODEL_NAME = (
    "sentence-transformers/paraphrase-multilingual-mpnet-base-v2"
)


@dataclass(frozen=True, slots=True)
class EmbeddingModelSpec:
    name: str
    dimension: int = 768
    query_prefix: str = ""
    passage_prefix: str = ""


SUPPORTED_EMBEDDING_MODELS: dict[str, EmbeddingModelSpec] = {
    E5_MODEL_NAME: EmbeddingModelSpec(
        name=E5_MODEL_NAME,
        query_prefix="query: ",
        passage_prefix="passage: ",
    ),
    LEGACY_MPNET_MODEL_NAME: EmbeddingModelSpec(
        name=LEGACY_MPNET_MODEL_NAME,
    ),
}


def get_embedding_model_spec(model_name: str) -> EmbeddingModelSpec:
    try:
        return SUPPORTED_EMBEDDING_MODELS[model_name]
    except KeyError as exc:
        supported = ", ".join(SUPPORTED_EMBEDDING_MODELS)
        raise ValueError(
            f"Unsupported embedding model {model_name!r}. Supported: {supported}"
        ) from exc
