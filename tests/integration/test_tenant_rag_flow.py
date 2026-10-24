import base64
import io
import json
import time
from collections.abc import Sequence
from pathlib import Path

from fastapi.testclient import TestClient
from pypdf import PdfWriter

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
        ids = []
        for word in text.split():
            if word not in self._word_to_id:
                token_id = len(self._word_to_id)
                self._word_to_id[word] = token_id
                self._id_to_word[token_id] = word
            ids.append(self._word_to_id[word])
        return ids

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


def _b64_json(value: dict[str, object]) -> str:
    encoded = base64.urlsafe_b64encode(json.dumps(value).encode()).decode()
    return encoded.rstrip("=")


def _token(tenant_id: str, secret: str, expires_at: int | None = None) -> str:
    header = _b64_json({"alg": "HS256", "typ": "JWT"})
    claims = _b64_json(
        {
            "tenant_id": tenant_id,
            "sub": f"user-{tenant_id}",
            "iss": "semantic-cache-rag",
            "aud": "semantic-cache-rag-api",
            "iat": int(time.time()),
            "exp": expires_at or int(time.time()) + 300,
        }
    )
    unsigned = f"{header}.{claims}".encode()
    import hashlib
    import hmac

    signature = hmac.new(secret.encode(), unsigned, hashlib.sha256).digest()
    encoded_signature = base64.urlsafe_b64encode(signature).decode().rstrip("=")
    return f"{header}.{claims}.{encoded_signature}"


def _pdf_fixture() -> bytes:
    writer = PdfWriter()
    writer.add_blank_page(width=72, height=72)
    output = io.BytesIO()
    writer.write(output)
    return output.getvalue()


def _test_client(tmp_path: Path) -> tuple[TestClient, str]:
    secret = "isolated-e2e-signing-key-with-32-bytes"
    settings = Settings(
        _env_file=None,
        APP_ENV="testing",
        REQUIRE_TENANT_AUTH=True,
        AUTH_SECRET_KEY=secret,
        CORPUS_DIR=str(tmp_path / "tenant-corpora"),
        QDRANT_LOCAL_PATH=str(tmp_path / "qdrant"),
        QDRANT_COLLECTION_DOCS="tenant_flow",
        DATABASE_URL=f"sqlite:///{tmp_path / 'metrics.sqlite3'}",
        CHUNK_SIZE=64,
        CHUNK_OVERLAP=4,
        SEMANTIC_CACHE_THRESHOLD=0.95,
        SEMANTIC_CACHE_TTL_SECONDS=60,
        max_document_bytes=1024,
        min_retrieval_score=0.2,
    )
    embedder = FakeEmbedder()
    vector_store = QdrantVectorStore(
        path=str(settings.qdrant_path),
        collection_name=settings.qdrant_collection,
        vector_size=embedder.dimension,
    )
    service = RagService(
        loader=DocumentLoader(settings.documents_dir, settings.max_document_bytes),
        chunker=TextChunker(embedder.tokenizer, settings.chunk_size_tokens, 4),
        embedder=embedder,
        vector_store=vector_store,
        answer_provider=ExtractiveAnswerProvider(),
        min_retrieval_score=settings.min_retrieval_score,
        semantic_cache_enabled=True,
        cache_threshold=settings.SEMANTIC_CACHE_THRESHOLD,
        cache_ttl_seconds=settings.SEMANTIC_CACHE_TTL_SECONDS,
        tenant_isolation_enabled=True,
    )
    return TestClient(create_app(settings=settings, service=service)), secret


def test_authenticated_tenant_upload_ingest_cache_and_invalidation(tmp_path: Path) -> None:
    client, secret = _test_client(tmp_path)
    tenant_a = {"Authorization": f"Bearer {_token('alpha', secret)}"}
    tenant_b = {"Authorization": f"Bearer {_token('bravo', secret)}"}
    signed_token_parts = _token("alpha", secret).split(".")
    signed_token_parts[-1] = (
        "A" if signed_token_parts[-1][0] != "A" else "B"
    ) + signed_token_parts[-1][1:]
    invalid_signature = ".".join(signed_token_parts)
    with client:
        assert client.get("/api/v1/documents").status_code == 401
        assert (
            client.get(
                "/api/v1/documents",
                headers={"Authorization": f"Bearer {invalid_signature}"},
            ).status_code
            == 401
        )
        assert (
            client.get(
                "/api/v1/documents",
                headers={"Authorization": f"Bearer {_token('../outside', secret)}"},
            ).status_code
            == 401
        )
        assert (
            client.get(
                "/api/v1/documents",
                headers={
                    "Authorization": f"Bearer {_token('alpha', secret, int(time.time()) - 1)}"
                },
            ).status_code
            == 401
        )

        text = (
            "RAG combines document retrieval with language generation. "
            "Citations identify the source document."
        )
        upload = client.post(
            "/api/v1/documents/upload",
            headers=tenant_a,
            files={"file": ("rag.txt", text.encode(), "text/plain")},
        )
        assert upload.status_code == 200
        pdf_upload = client.post(
            "/api/v1/documents/upload",
            headers=tenant_a,
            files={"file": ("blank.pdf", _pdf_fixture(), "application/pdf")},
        )
        assert pdf_upload.status_code == 200

        listed_a = client.get("/api/v1/documents", headers=tenant_a)
        listed_b = client.get("/api/v1/documents", headers=tenant_b)
        assert {item["name"] for item in listed_a.json()["documents"]} == {"rag.txt", "blank.pdf"}
        assert listed_b.json()["documents"] == []

        first_ingest = client.post("/api/v1/ingest", headers=tenant_a)
        assert first_ingest.status_code == 200
        assert first_ingest.json()["documents_ingested"] == 1
        first = client.post(
            "/api/v1/ask",
            headers=tenant_a,
            json={"query": "What is RAG?", "top_k": 5},
        )
        assert first.status_code == 200
        assert first.json()["status"] == "supported"
        assert first.json()["cache_hit"] is False
        assert first.json()["citations"][0]["source_path"] == "rag.txt"

        hit = client.post(
            "/api/v1/ask",
            headers=tenant_a,
            json={"query": "What is RAG?", "top_k": 5},
        )
        assert hit.json()["cache_hit"] is True
        assert hit.json()["citations"] == first.json()["citations"]

        other_tenant = client.post(
            "/api/v1/ask",
            headers=tenant_b,
            json={"query": "What is RAG?", "top_k": 5},
        )
        assert other_tenant.json()["status"] == "insufficient_evidence"
        assert other_tenant.json()["cache_hit"] is False

        stats = client.get("/api/v1/cache/stats", headers=tenant_a).json()
        assert stats["total_entries"] == 1
        assert stats["hits"] == 1
        assert stats["misses"] == 1

        assert client.post("/api/v1/cache/invalidate", headers=tenant_a).status_code == 200
        assert client.get("/api/v1/cache/stats", headers=tenant_a).json()["total_entries"] == 0
        assert (
            client.post(
                "/api/v1/ask",
                headers=tenant_a,
                json={"query": "What is RAG?", "top_k": 5},
            ).json()["cache_hit"]
            is False
        )

        changed = client.post(
            "/api/v1/documents/upload",
            headers=tenant_a,
            files={
                "file": (
                    "extra.txt",
                    b"Vector retrieval ranks passages by semantic relevance.",
                    "text/plain",
                )
            },
        )
        assert changed.status_code == 200
        assert client.get("/api/v1/cache/stats", headers=tenant_a).json()["total_entries"] == 0
        assert (
            client.post(
                "/api/v1/ask",
                headers=tenant_a,
                json={"query": "What is RAG?", "top_k": 5},
            ).json()["status"]
            == "insufficient_evidence"
        )

        second_ingest = client.post("/api/v1/ingest", headers=tenant_a)
        assert second_ingest.status_code == 200
        assert second_ingest.json()["corpus_version"] != first_ingest.json()["corpus_version"]
        assert client.get("/api/v1/cache/stats", headers=tenant_a).json()["total_entries"] == 0
        assert (
            client.post(
                "/api/v1/ask",
                headers=tenant_a,
                json={"query": "What is RAG?", "top_k": 5},
            ).json()["status"]
            == "supported"
        )

        metrics_a = client.get("/api/v1/metrics", headers=tenant_a).json()
        metrics_b = client.get("/api/v1/metrics", headers=tenant_b).json()
        assert metrics_a["cache_hit_count"] == 1
        assert metrics_a["total_requests"] == 5
        assert metrics_b["total_requests"] == 1
        assert metrics_a["indexed_documents"] == 2

        deleted = client.delete("/api/v1/documents/rag.txt", headers=tenant_a)
        assert deleted.status_code == 200
        assert (
            client.post(
                "/api/v1/ask",
                headers=tenant_a,
                json={"query": "What is RAG?", "top_k": 5},
            ).json()["status"]
            == "insufficient_evidence"
        )
        metrics_after_delete = client.get("/api/v1/metrics", headers=tenant_a).json()
        assert metrics_after_delete["indexed_documents"] == 0
        assert metrics_after_delete["indexed_chunks"] == 0


def test_upload_rejects_traversal_oversize_and_malformed_content(tmp_path: Path) -> None:
    client, secret = _test_client(tmp_path)
    headers = {"Authorization": f"Bearer {_token('alpha', secret)}"}
    with client:
        traversal = client.post(
            "/api/v1/documents/upload",
            headers=headers,
            files={"file": ("../escape.txt", b"unsafe content", "text/plain")},
        )
        assert traversal.status_code == 400
        reserved_name = client.post(
            "/api/v1/documents/upload",
            headers=headers,
            files={"file": ("NUL.txt", b"unsafe name", "text/plain")},
        )
        assert reserved_name.status_code == 400
        oversized = client.post(
            "/api/v1/documents/upload",
            headers=headers,
            files={"file": ("large.txt", b"x" * 1025, "text/plain")},
        )
        assert oversized.status_code == 413
        request_too_large = client.post(
            "/api/v1/documents/upload",
            headers=headers,
            files={
                "file": (
                    "request-too-large.txt",
                    b"x" * (1024 * 1024 + 1025),
                    "text/plain",
                )
            },
        )
        assert request_too_large.status_code == 413
        invalid_pdf = client.post(
            "/api/v1/documents/upload",
            headers=headers,
            files={"file": ("broken.pdf", b"not a pdf", "application/pdf")},
        )
        assert invalid_pdf.status_code == 400
        unsafe_delete = client.delete(
            "/api/v1/documents/..%5C..%5Csecret.txt",
            headers=headers,
        )
        assert unsafe_delete.status_code in {400, 404}
