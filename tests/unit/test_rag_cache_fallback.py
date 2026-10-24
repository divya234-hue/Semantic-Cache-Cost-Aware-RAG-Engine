from collections.abc import Sequence

from backend.app.models.domain import DocumentChunk, RetrievedChunk
from backend.app.services.answer_provider import ExtractiveAnswerProvider
from backend.app.services.chunking import TextChunker
from backend.app.services.document_loader import DocumentLoader
from backend.app.services.rag_service import RagService


class Tokenizer:
    def encode(
        self, text: str, *, add_special_tokens: bool = False, truncation: bool = False
    ) -> list[int]:
        del add_special_tokens, truncation
        return list(range(len(text.split())))

    def decode(
        self,
        token_ids: Sequence[int],
        *,
        skip_special_tokens: bool = True,
        clean_up_tokenization_spaces: bool = True,
    ) -> str:
        del token_ids, skip_special_tokens, clean_up_tokenization_spaces
        return ""


class Embedder:
    tokenizer = Tokenizer()

    @property
    def dimension(self) -> int:
        return 2

    def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        return [[1.0, 0.0] for _ in texts]

    def embed_query(self, text: str) -> list[float]:
        del text
        return [1.0, 0.0]


class CacheUnavailableStore:
    def current_corpus_version(self, tenant_id: str) -> str:
        del tenant_id
        return "version-1"

    def search_cache(self, *args) -> None:
        del args
        raise RuntimeError("cache is unavailable")

    def upsert_cache(self, *args) -> None:
        del args
        raise RuntimeError("cache is unavailable")

    def search(
        self,
        vector: Sequence[float],
        limit: int,
        tenant_id: str = "tenant-default",
        corpus_version: str | None = None,
    ) -> list[RetrievedChunk]:
        del vector, limit, tenant_id, corpus_version
        return [
            RetrievedChunk(
                DocumentChunk(
                    "doc",
                    "chunk-1",
                    "rag.txt",
                    "version-1",
                    "RAG combines document retrieval with language generation.",
                    8,
                ),
                0.95,
            )
        ]


def test_cache_failure_falls_back_to_retrieval_and_answer(tmp_path) -> None:
    embedder = Embedder()
    service = RagService(
        loader=DocumentLoader(tmp_path, 1024),
        chunker=TextChunker(embedder.tokenizer, 32, 2),
        embedder=embedder,
        vector_store=CacheUnavailableStore(),
        answer_provider=ExtractiveAnswerProvider(),
        min_retrieval_score=0.2,
        semantic_cache_enabled=True,
        cache_threshold=0.9,
        cache_ttl_seconds=60,
    )

    result = service.ask("What is RAG?", 5)

    assert result["status"] == "supported"
    assert result["cache_hit"] is False
    assert result["citations"][0]["source_path"] == "rag.txt"
