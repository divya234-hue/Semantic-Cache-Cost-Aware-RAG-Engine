from collections.abc import Sequence


class SentenceTransformerEmbedder:
    def __init__(self, model_name: str) -> None:
        from sentence_transformers import SentenceTransformer

        self.model = SentenceTransformer(model_name)
        max_positions = getattr(
            self.model[0].auto_model.config,
            "max_position_embeddings",
            self.model.max_seq_length,
        )
        self.max_seq_length = min(int(max_positions), 512)
        self.model.max_seq_length = self.max_seq_length

    @property
    def tokenizer(self):
        return self.model.tokenizer

    @property
    def dimension(self) -> int:
        dimension = self.model.get_sentence_embedding_dimension()
        if dimension is None:
            raise RuntimeError("The configured embedding model does not expose a vector size.")
        return dimension

    def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        vectors = self.model.encode(
            list(texts),
            normalize_embeddings=True,
            convert_to_numpy=True,
            show_progress_bar=False,
            batch_size=16,
        )
        return vectors.tolist()

    def embed_query(self, text: str) -> list[float]:
        return self.embed_documents([text])[0]
