from collections.abc import Sequence
from pathlib import Path

from fastapi.testclient import TestClient

from backend.app.core.config import Settings
from backend.app.main import create_app
from backend.app.repositories.qdrant_vector_store import QdrantVectorStore
from backend.app.services.answer_provider import ExtractiveAnswerProvider
from backend.app.services.chunking import TextChunker
from backend.app.services.document_loader import DocumentLoader
from backend.app.services.rag_service import RagService


class WordTokenizer:
    def __init__(self) -> None:
        self._word_to_id: dict[str, int] = {}
        self._id_to_word: dict[int, str] = {}

    def encode(
        self,
        text: str,
        *,
        add_special_tokens: bool = False,
        truncation: bool = False,
    ) -> list[int]:
        del add_special_tokens, truncation
        token_ids: list[int] = []
        for word in text.split():
            if word not in self._word_to_id:
                token_id = len(self._word_to_id)
                self._word_to_id[word] = token_id
                self._id_to_word[token_id] = word
            token_ids.append(self._word_to_id[word])
        return token_ids

    def decode(
        self,
        token_ids: Sequence[int],
        *,
        skip_special_tokens: bool = True,
        clean_up_tokenization_spaces: bool = True,
    ) -> str:
        del skip_special_tokens, clean_up_tokenization_spaces
        return " ".join(self._id_to_word[token_id] for token_id in token_ids)


class FakeEmbedder:
    tokenizer = WordTokenizer()
    dimension = 2

    def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        return [[1.0, 0.0] for _ in texts]

    def embed_query(self, text: str) -> list[float]:
        del text
        return [1.0, 0.0]


def test_ingest_and_ask_end_to_end_with_local_qdrant(tmp_path: Path) -> None:
    settings = Settings(
        _env_file=None,
        APP_ENV="testing",
        CORPUS_DIR=str(tmp_path / "documents"),
        qdrant_path=tmp_path / "qdrant",
        DATABASE_URL=f"sqlite:///{tmp_path / 'metrics.sqlite3'}",
        chunk_size_tokens=32,
        chunk_overlap_tokens=4,
        min_retrieval_score=0.2,
    )
    tenant_documents = settings.tenant_documents_dir(settings.DEFAULT_TENANT_ID)
    tenant_documents.mkdir(parents=True)
    (tenant_documents / "rag.txt").write_text(
        "RAG combines document retrieval with language generation. "
        "Citations identify the source document.",
        encoding="utf-8",
    )
    vector_store = QdrantVectorStore(
        path=str(settings.qdrant_path),
        collection_name="test_rag",
        vector_size=2,
    )
    service = RagService(
        loader=DocumentLoader(settings.documents_dir, settings.max_document_bytes),
        chunker=TextChunker(FakeEmbedder.tokenizer, 32, 4),
        embedder=FakeEmbedder(),
        vector_store=vector_store,
        answer_provider=ExtractiveAnswerProvider(),
        min_retrieval_score=settings.min_retrieval_score,
    )

    with TestClient(create_app(settings=settings, service=service)) as client:
        missing = client.post("/api/v1/ask", json={"query": "What is RAG?"})
        assert missing.status_code == 200
        assert missing.json()["status"] == "insufficient_evidence"

        ingested = client.post("/api/v1/ingest")
        assert ingested.status_code == 200
        assert ingested.json()["documents_ingested"] == 1
        assert ingested.json()["chunks_indexed"] >= 1

        answer = client.post("/api/v1/ask", json={"query": "What is RAG?"})
        assert answer.status_code == 200
        body = answer.json()
        assert body["status"] == "supported"
        assert "RAG combines document retrieval" in body["answer"]
        assert body["citations"][0]["source_path"] == "rag.txt"


def test_request_validation_and_health_endpoints(tmp_path: Path) -> None:
    settings = Settings(
        _env_file=None,
        APP_ENV="testing",
        CORPUS_DIR=str(tmp_path / "documents"),
        qdrant_path=tmp_path / "qdrant",
        DATABASE_URL=f"sqlite:///{tmp_path / 'metrics.sqlite3'}",
    )
    vector_store = QdrantVectorStore(
        path=str(settings.qdrant_path),
        collection_name="test_health",
        vector_size=2,
    )
    service = RagService(
        loader=DocumentLoader(settings.documents_dir, settings.max_document_bytes),
        chunker=TextChunker(FakeEmbedder.tokenizer, 32, 4),
        embedder=FakeEmbedder(),
        vector_store=vector_store,
        answer_provider=ExtractiveAnswerProvider(),
        min_retrieval_score=settings.min_retrieval_score,
    )

    with TestClient(create_app(settings=settings, service=service)) as client:
        assert client.get("/health").json() == {"status": "ok"}
        assert client.get("/ready").json() == {"status": "ready"}
        assert client.post("/api/v1/ask", json={"query": "  "}).status_code == 422
        assert client.post("/api/v1/ask", json={"query": "two"}).status_code == 422
