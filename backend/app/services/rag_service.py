import hashlib
import logging
import threading
import weakref
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from typing import Protocol

from qdrant_client.http.exceptions import (
    ApiException,
    ResponseHandlingException,
    UnexpectedResponse,
)

from backend.app.models.domain import (
    AnswerResult,
    DocumentChunk,
    LoadedDocument,
    RetrievedChunk,
)
from backend.app.services.chunking import TextChunker
from backend.app.services.document_loader import DocumentLoader, NoDocumentsFoundError

logger = logging.getLogger(__name__)
_CACHE_ERRORS = (
    ApiException,
    OSError,
    ResponseHandlingException,
    RuntimeError,
    UnexpectedResponse,
    ValueError,
)

INSUFFICIENT_EVIDENCE_ANSWER = (
    "I don't have enough evidence in the indexed documents to answer this question."
)


class Embedder(Protocol):
    @property
    def tokenizer(self): ...

    @property
    def dimension(self) -> int: ...

    def embed_documents(self, texts: Sequence[str]) -> list[list[float]]: ...

    def embed_query(self, text: str) -> list[float]: ...


class VectorStore(Protocol):
    def upsert_corpus(
        self,
        chunks: Sequence[DocumentChunk],
        vectors: Sequence[Sequence[float]],
        corpus_version: str,
    ) -> None: ...

    def search(
        self,
        vector: Sequence[float],
        limit: int,
        tenant_id: str = "tenant-default",
        corpus_version: str | None = None,
    ) -> list[RetrievedChunk]: ...


class AnswerProvider(Protocol):
    name: str

    def generate(
        self,
        query: str,
        retrieved_chunks: Sequence[RetrievedChunk],
    ) -> AnswerResult | None: ...


class RagService:
    def __init__(
        self,
        loader: DocumentLoader,
        chunker: TextChunker,
        embedder: Embedder,
        vector_store: VectorStore,
        answer_provider: AnswerProvider,
        min_retrieval_score: float,
        semantic_cache_enabled: bool = True,
        cache_threshold: float = 0.9,
        cache_ttl_seconds: int = 86400,
        confidence_threshold: float = 0.0,
        tenant_isolation_enabled: bool = False,
    ) -> None:
        self.loader = loader
        self.chunker = chunker
        self.embedder = embedder
        self.vector_store = vector_store
        self.answer_provider = answer_provider
        self.min_retrieval_score = min_retrieval_score
        self.semantic_cache_enabled = semantic_cache_enabled
        self.cache_threshold = cache_threshold
        self.cache_ttl_seconds = cache_ttl_seconds
        self.confidence_threshold = confidence_threshold
        self.tenant_isolation_enabled = tenant_isolation_enabled
        self._tenant_locks: weakref.WeakValueDictionary[str, threading.RLock] = (
            weakref.WeakValueDictionary()
        )
        self._tenant_locks_guard = threading.Lock()
        self._invalidated_tenants: set[str] = set()
        self._indexed_document_counts: dict[str, tuple[str, int]] = {}

    @contextmanager
    def tenant_corpus_lock(self, tenant_id: str) -> Iterator[None]:
        with self._tenant_locks_guard:
            lock = self._tenant_locks.get(tenant_id)
            if lock is None:
                lock = threading.RLock()
                self._tenant_locks[tenant_id] = lock
        with lock:
            yield

    def tenant_documents_dir(self, tenant_id: str):
        if not self.tenant_isolation_enabled and tenant_id == "tenant-default":
            return self.loader.documents_dir
        tenant_key = hashlib.sha256(tenant_id.encode("utf-8")).hexdigest()[:32]
        return self.loader.documents_dir / "_tenants" / tenant_key

    def ingest(self, tenant_id: str = "tenant-default") -> tuple[int, int, str]:
        with self.tenant_corpus_lock(tenant_id):
            self.invalidate_tenant(tenant_id)
            loader = DocumentLoader(
                self.tenant_documents_dir(tenant_id),
                self.loader.max_document_bytes,
            )
            documents = loader.load_all()
            if not documents:
                raise NoDocumentsFoundError(
                    "No non-empty TXT or PDF documents were found in the configured corpus."
                )

            corpus_version = self._corpus_version(documents)
            chunks = self.chunker.split_documents(documents, corpus_version)
            if not chunks:
                raise NoDocumentsFoundError("The corpus did not produce any indexable text chunks.")
            vectors = self.embedder.embed_documents([chunk.text for chunk in chunks])
            self.vector_store.upsert_corpus(chunks, vectors, corpus_version, tenant_id=tenant_id)
            self._invalidated_tenants.discard(tenant_id)
            self._indexed_document_counts[tenant_id] = (corpus_version, len(documents))
            return len(documents), len(chunks), corpus_version

    def ask(
        self,
        query: str,
        top_k: int,
        tenant_id: str = "tenant-default",
    ) -> dict[str, object]:
        with self.tenant_corpus_lock(tenant_id):
            return self._ask_locked(query, top_k, tenant_id)

    def _ask_locked(self, query: str, top_k: int, tenant_id: str) -> dict[str, object]:
        corpus_invalidated = tenant_id in self._invalidated_tenants
        if corpus_invalidated:
            return {
                "status": "insufficient_evidence",
                "answer": INSUFFICIENT_EVIDENCE_ANSWER,
                "citations": [],
                "provider": self.answer_provider.name,
                "cache_hit": False,
                "route": "cheap",
                "escalated": False,
                "cost_usd": 0.0,
                "input_tokens": 0,
                "output_tokens": 0,
            }
        query_vector = self.embedder.embed_query(query)
        current_version = getattr(
            self.vector_store, "current_corpus_version", lambda _tenant: None
        )(tenant_id)
        cache_lookup = getattr(self.vector_store, "search_cache", None)
        cache_write = getattr(self.vector_store, "upsert_cache", None)
        if self.semantic_cache_enabled and current_version and cache_lookup is not None:
            try:
                cached = cache_lookup(
                    query_vector, tenant_id, current_version, self.cache_threshold
                )
            except _CACHE_ERRORS as exc:
                logger.warning(
                    "Semantic cache lookup unavailable (%s); continuing without cache.",
                    type(exc).__name__,
                )
            else:
                if cached is not None:
                    response, _score = cached
                    return {
                        **response,
                        "cache_hit": True,
                        "cost_usd": 0.0,
                        "input_tokens": 0,
                        "output_tokens": 0,
                    }

        retrieved = self.vector_store.search(
            query_vector,
            top_k,
            tenant_id=tenant_id,
            corpus_version=current_version,
        )
        eligible = [chunk for chunk in retrieved if chunk.score >= self.min_retrieval_score]
        answer_result = self.answer_provider.generate(query, eligible) if eligible else None
        if answer_result is None:
            result = {
                "status": "insufficient_evidence",
                "answer": INSUFFICIENT_EVIDENCE_ANSWER,
                "citations": [],
                "provider": self.answer_provider.name,
                "cache_hit": False,
                "route": "cheap",
                "escalated": False,
                "cost_usd": 0.0,
                "input_tokens": 0,
                "output_tokens": 0,
            }
            return self._cache_result(result, query_vector, tenant_id, current_version, cache_write)

        citations = [
            {
                "document_id": item.chunk.document_id,
                "chunk_id": item.chunk.chunk_id,
                "source_path": item.chunk.source_path,
                "retrieval_score": item.score,
            }
            for item in eligible
            if item.chunk.chunk_id in answer_result.source_chunk_ids
        ]
        if not citations:
            result = {
                "status": "insufficient_evidence",
                "answer": INSUFFICIENT_EVIDENCE_ANSWER,
                "citations": [],
                "provider": self.answer_provider.name,
                "cache_hit": False,
                "route": "cheap",
                "escalated": False,
                "cost_usd": 0.0,
                "input_tokens": 0,
                "output_tokens": 0,
            }
        elif answer_result.confidence < self.confidence_threshold:
            result = {
                "status": "insufficient_evidence",
                "answer": INSUFFICIENT_EVIDENCE_ANSWER,
                "citations": [],
                "provider": answer_result.provider_name or self.answer_provider.name,
                "model": answer_result.model_name,
                "cache_hit": False,
                "route": answer_result.route,
                "escalated": answer_result.escalated,
                "cost_usd": answer_result.cost_usd,
                "input_tokens": answer_result.input_tokens,
                "output_tokens": answer_result.output_tokens,
            }
        else:
            result = {
                "status": "supported",
                "answer": answer_result.answer,
                "citations": citations,
                "provider": answer_result.provider_name or self.answer_provider.name,
                "model": answer_result.model_name,
                "cache_hit": False,
                "route": answer_result.route,
                "escalated": answer_result.escalated,
                "cost_usd": answer_result.cost_usd,
                "input_tokens": answer_result.input_tokens,
                "output_tokens": answer_result.output_tokens,
            }
        return self._cache_result(result, query_vector, tenant_id, current_version, cache_write)

    def invalidate_tenant(self, tenant_id: str) -> None:
        with self.tenant_corpus_lock(tenant_id):
            self._invalidated_tenants.add(tenant_id)
            self._indexed_document_counts.pop(tenant_id, None)
            invalidate = getattr(self.vector_store, "invalidate_tenant", None)
            if invalidate is not None:
                invalidate(tenant_id)

    def invalidate_cache(self, tenant_id: str) -> None:
        with self.tenant_corpus_lock(tenant_id):
            invalidate = getattr(self.vector_store, "invalidate_cache", None)
            if invalidate is not None:
                invalidate(tenant_id)

    def chunk_count(self, tenant_id: str) -> int:
        with self.tenant_corpus_lock(tenant_id):
            version = getattr(self.vector_store, "current_corpus_version", lambda _tenant: None)(
                tenant_id
            )
            count = getattr(self.vector_store, "chunk_count", None)
            return count(tenant_id, version) if count is not None else 0

    def document_count(self, tenant_id: str) -> int:
        with self.tenant_corpus_lock(tenant_id):
            version = getattr(self.vector_store, "current_corpus_version", lambda _tenant: None)(
                tenant_id
            )
            if not version:
                return 0
            cached = self._indexed_document_counts.get(tenant_id)
            if cached and cached[0] == version:
                return cached[1]
            count = getattr(self.vector_store, "document_count", None)
            if count is None:
                return 0
            document_count = count(tenant_id, version)
            self._indexed_document_counts[tenant_id] = (version, document_count)
            return document_count

    def _cache_result(
        self,
        result: dict[str, object],
        vector: Sequence[float],
        tenant_id: str,
        corpus_version: str | None,
        cache_write,
    ) -> dict[str, object]:
        if not self.semantic_cache_enabled or not corpus_version or cache_write is None:
            return result
        try:
            cache_write(
                vector,
                result,
                tenant_id,
                corpus_version,
                self.cache_ttl_seconds,
            )
        except _CACHE_ERRORS as exc:
            logger.warning("Semantic cache write unavailable (%s).", type(exc).__name__)
        return result

    @staticmethod
    def _corpus_version(documents: Sequence[LoadedDocument]) -> str:
        digest = hashlib.sha256()
        for document in sorted(documents, key=lambda item: item.source_path):
            digest.update(document.source_path.encode("utf-8"))
            digest.update(b"\0")
            digest.update(document.text.encode("utf-8"))
            digest.update(b"\0")
        return digest.hexdigest()
