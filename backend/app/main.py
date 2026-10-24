import logging
import threading
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from backend.app.api.routes import router
from backend.app.core.config import Settings
from backend.app.core.security import TenantRateLimiter
from backend.app.repositories.qdrant_vector_store import QdrantVectorStore
from backend.app.services.answer_provider import ExtractiveAnswerProvider, RoutedAnswerProvider
from backend.app.services.chunking import TextChunker
from backend.app.services.document_loader import DocumentLoader
from backend.app.services.embeddings import SentenceTransformerEmbedder
from backend.app.services.metrics_store import MetricsStore
from backend.app.services.rag_service import RagService

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)


class UploadSizeExceeded(Exception):
    pass


class UploadRequestSizeMiddleware:
    def __init__(self, app: ASGIApp, max_file_bytes: int) -> None:
        self.app = app
        self.max_request_bytes = max_file_bytes + 1024 * 1024

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if (
            scope["type"] != "http"
            or scope["method"] != "POST"
            or scope["path"] != "/api/v1/documents/upload"
        ):
            await self.app(scope, receive, send)
            return

        content_length = next(
            (
                value
                for name, value in scope.get("headers", [])
                if name.lower() == b"content-length"
            ),
            None,
        )
        if content_length is not None:
            try:
                if int(content_length) > self.max_request_bytes:
                    await self._reject(send)
                    return
            except ValueError:
                await self._reject(send, 400, b'{"detail":"Invalid Content-Length."}')
                return

        total_bytes = 0

        async def limited_receive() -> Message:
            nonlocal total_bytes
            message = await receive()
            total_bytes += len(message.get("body", b""))
            if total_bytes > self.max_request_bytes:
                raise UploadSizeExceeded
            return message

        try:
            await self.app(scope, limited_receive, send)
        except UploadSizeExceeded:
            await self._reject(send)

    @staticmethod
    async def _reject(
        send: Send,
        status_code: int = 413,
        body: bytes = b'{"detail":"Uploaded request exceeds the configured size limit."}',
    ) -> None:
        await send(
            {
                "type": "http.response.start",
                "status": status_code,
                "headers": [(b"content-type", b"application/json")],
            }
        )
        await send({"type": "http.response.body", "body": body})


class LazyASGIApplication:
    def __init__(self) -> None:
        self._application: ASGIApp | None = None
        self._lock = threading.Lock()

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if self._application is None:
            with self._lock:
                if self._application is None:
                    self._application = create_app()
        await self._application(scope, receive, send)


def build_rag_service(settings: Settings) -> RagService:
    embedder = SentenceTransformerEmbedder(settings.embedding_model)
    qdrant_path: str | None = None
    qdrant_url: str | None = None
    if settings.QDRANT_USE_LOCAL_STORAGE:
        settings.qdrant_path.parent.mkdir(parents=True, exist_ok=True)
        qdrant_path = str(settings.qdrant_path)
    else:
        qdrant_url = settings.qdrant_url
    vector_store = QdrantVectorStore(
        path=qdrant_path,
        collection_name=settings.qdrant_collection,
        vector_size=embedder.dimension,
        url=qdrant_url,
        api_key=settings.QDRANT_API_KEY,
        cache_collection_name=settings.QDRANT_COLLECTION_CACHE,
    )
    answer_provider = RoutedAnswerProvider(settings, ExtractiveAnswerProvider())
    return RagService(
        loader=DocumentLoader(settings.documents_dir, settings.max_document_bytes),
        chunker=TextChunker(
            tokenizer=embedder.tokenizer,
            chunk_size_tokens=settings.chunk_size_tokens,
            overlap_tokens=settings.chunk_overlap_tokens,
        ),
        embedder=embedder,
        vector_store=vector_store,
        answer_provider=answer_provider,
        min_retrieval_score=settings.min_retrieval_score,
        semantic_cache_enabled=settings.SEMANTIC_CACHE_ENABLED,
        cache_threshold=settings.SEMANTIC_CACHE_THRESHOLD,
        cache_ttl_seconds=settings.SEMANTIC_CACHE_TTL_SECONDS,
        confidence_threshold=settings.CONFIDENCE_THRESHOLD,
        tenant_isolation_enabled=settings.REQUIRE_TENANT_AUTH,
    )


def create_app(
    settings: Settings | None = None,
    service: RagService | None = None,
) -> FastAPI:
    app_settings = settings or Settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        app.state.settings = app_settings
        metrics_store = MetricsStore(
            app_settings.metrics_db_path,
            app_settings.MAX_METRIC_RECORDS,
        )
        app.state.metrics_store = metrics_store
        app.state.rate_limiter = TenantRateLimiter(app_settings.RATE_LIMIT_REQUESTS_PER_MINUTE)
        try:
            app.state.rag_service = service or build_rag_service(app_settings)
            yield
        finally:
            metrics_store.close()
            rag_service = getattr(app.state, "rag_service", None)
            vector_store = getattr(rag_service, "vector_store", None)
            client = getattr(vector_store, "client", None)
            if client is not None:
                client.close()
            provider = getattr(rag_service, "answer_provider", None)
            close_provider = getattr(provider, "close", None)
            if close_provider is not None:
                close_provider()

    app = FastAPI(
        title="Semantic Cache & Cost-Aware RAG Engine",
        version="0.1.0",
        description="A local, citation-grounded baseline RAG API.",
        lifespan=lifespan,
    )
    app.add_middleware(
        UploadRequestSizeMiddleware,
        max_file_bytes=app_settings.max_document_bytes,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=app_settings.CORS_ALLOWED_ORIGINS,
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["Authorization", "Content-Type"],
    )
    app.include_router(router)
    return app


app = LazyASGIApplication()
