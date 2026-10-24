import datetime
import io
import logging
import os
import uuid
from pathlib import Path, PureWindowsPath
from time import perf_counter
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request
from pypdf import PdfReader
from pypdf.errors import PdfReadError
from qdrant_client.http.exceptions import (
    ApiException,
    ResponseHandlingException,
    UnexpectedResponse,
)
from starlette.datastructures import UploadFile

from backend.app.core.config import Settings
from backend.app.core.security import TenantContext, require_tenant
from backend.app.schemas.api import (
    AskRequest,
    AskResponse,
    CacheStatsResponse,
    DocumentDeleteResponse,
    DocumentInfo,
    DocumentListResponse,
    DocumentUploadResponse,
    HealthResponse,
    IngestResponse,
    MetricsSummaryResponse,
    SystemSettingsResponse,
)
from backend.app.services.answer_provider import ProviderError
from backend.app.services.document_loader import DocumentLoadError, NoDocumentsFoundError
from backend.app.services.metrics_store import MetricsStore
from backend.app.services.rag_service import RagService

logger = logging.getLogger(__name__)
router = APIRouter()
_WINDOWS_RESERVED_NAMES = {
    "AUX",
    "CON",
    "NUL",
    "PRN",
    *(f"COM{number}" for number in range(1, 10)),
    *(f"LPT{number}" for number in range(1, 10)),
}


def _is_safe_filename(filename: str) -> bool:
    if (
        not filename
        or len(filename) > 255
        or filename in {".", ".."}
        or "/" in filename
        or "\\" in filename
        or any(ord(character) < 32 or character in '<>:"|?*' for character in filename)
        or filename.endswith((" ", "."))
        or PureWindowsPath(filename).name != filename
    ):
        return False
    return PureWindowsPath(filename).stem.upper() not in _WINDOWS_RESERVED_NAMES


def get_rag_service(request: Request) -> RagService:
    service = getattr(request.app.state, "rag_service", None)
    if service is None:
        raise HTTPException(status_code=503, detail="RAG service is not ready.")
    return service


def get_settings(request: Request) -> Settings:
    return request.app.state.settings


def get_metrics_store(request: Request) -> MetricsStore:
    store = getattr(request.app.state, "metrics_store", None)
    if store is None:
        raise HTTPException(status_code=503, detail="Metrics service is not ready.")
    return store


def get_tenant(request: Request) -> TenantContext:
    tenant = require_tenant(request)
    request.app.state.rate_limiter.check(tenant.tenant_id)
    return tenant


@router.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    return HealthResponse(status="ok")


@router.get("/ready", response_model=HealthResponse)
def readiness(
    service: Annotated[RagService, Depends(get_rag_service)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> HealthResponse:
    qdrant_client = getattr(service.vector_store, "client", None)
    if qdrant_client is not None:
        try:
            qdrant_client.get_collections()
        except (
            ApiException,
            OSError,
            ResponseHandlingException,
            RuntimeError,
            UnexpectedResponse,
        ) as exc:
            logger.warning("Qdrant readiness check failed (%s).", type(exc).__name__)
            raise HTTPException(status_code=503, detail="Vector storage is unavailable.") from exc
    if settings.LLM_PROVIDER != "mock" and settings.LLM_PROVIDER != "ollama":
        configured_key = {
            "openai": settings.OPENAI_API_KEY,
            "groq": settings.GROQ_API_KEY,
            "gemini": settings.GEMINI_API_KEY,
        }.get(settings.LLM_PROVIDER)
        if not configured_key:
            raise HTTPException(
                status_code=503, detail="Answer provider configuration is incomplete."
            )
    del service
    return HealthResponse(status="ready")


@router.post("/api/v1/ingest", response_model=IngestResponse)
def ingest_documents(
    service: Annotated[RagService, Depends(get_rag_service)],
    tenant: Annotated[TenantContext, Depends(get_tenant)],
) -> IngestResponse:
    try:
        document_count, chunk_count, corpus_version = service.ingest(tenant.tenant_id)
    except NoDocumentsFoundError as exc:
        logger.info("Document ingestion was rejected for a tenant.")
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except DocumentLoadError as exc:
        logger.warning("Document ingestion could not read a corpus document.")
        raise HTTPException(
            status_code=422,
            detail="One or more corpus documents could not be read.",
        ) from exc
    return IngestResponse(
        documents_ingested=document_count,
        chunks_indexed=chunk_count,
        corpus_version=corpus_version,
    )


@router.post("/api/v1/ask", response_model=AskResponse)
def ask(
    payload: AskRequest,
    service: Annotated[RagService, Depends(get_rag_service)],
    settings: Annotated[Settings, Depends(get_settings)],
    tenant: Annotated[TenantContext, Depends(get_tenant)],
    metrics: Annotated[MetricsStore, Depends(get_metrics_store)],
) -> AskResponse:
    started = perf_counter()
    try:
        result = service.ask(payload.query, payload.top_k or settings.top_k, tenant.tenant_id)
    except ProviderError as exc:
        logger.warning("Configured answer provider failed (%s).", type(exc).__name__)
        raise HTTPException(
            status_code=502,
            detail="The configured answer provider is temporarily unavailable.",
        ) from exc
    elapsed_ms = (perf_counter() - started) * 1000
    metrics.record(
        tenant.tenant_id,
        elapsed_ms,
        bool(result.get("cache_hit", False)),
        "cache" if result.get("cache_hit", False) else str(result.get("route", "cheap")),
        bool(result.get("escalated", False)),
        float(result.get("cost_usd", 0.0)),
        int(result.get("input_tokens", 0)),
        int(result.get("output_tokens", 0)),
    )
    return AskResponse.model_validate(result)


@router.get("/api/v1/settings", response_model=SystemSettingsResponse)
def get_system_settings(
    settings: Annotated[Settings, Depends(get_settings)],
    service: Annotated[RagService, Depends(get_rag_service)],
    tenant: Annotated[TenantContext, Depends(get_tenant)],
) -> SystemSettingsResponse:
    return SystemSettingsResponse(
        app_name=settings.APP_NAME,
        app_env=settings.APP_ENV,
        log_level=settings.LOG_LEVEL,
        corpus_dir=str(service.tenant_documents_dir(tenant.tenant_id)),
        corpus_version=service.vector_store.current_corpus_version(tenant.tenant_id)
        if hasattr(service.vector_store, "current_corpus_version")
        else settings.CORPUS_VERSION,
        embedding_model=settings.embedding_model,
        embedding_dimension=settings.EMBEDDING_DIMENSION,
        qdrant_local_path=str(settings.qdrant_path),
        qdrant_collection=settings.qdrant_collection,
        semantic_cache_enabled=settings.SEMANTIC_CACHE_ENABLED,
        cache_threshold=settings.SEMANTIC_CACHE_THRESHOLD,
        cache_ttl_seconds=settings.SEMANTIC_CACHE_TTL_SECONDS,
        llm_provider=settings.LLM_PROVIDER,
        cheap_model=settings.CHEAP_MODEL_NAME,
        strong_model=settings.STRONG_MODEL_NAME,
        escalation_enabled=settings.ESCALATION_ENABLED,
        cheap_input_price=settings.CHEAP_MODEL_INPUT_PRICE_PER_1M,
        cheap_output_price=settings.CHEAP_MODEL_OUTPUT_PRICE_PER_1M,
        strong_input_price=settings.STRONG_MODEL_INPUT_PRICE_PER_1M,
        strong_output_price=settings.STRONG_MODEL_OUTPUT_PRICE_PER_1M,
        tenant_auth_enabled=settings.REQUIRE_TENANT_AUTH,
    )


@router.get("/api/v1/documents", response_model=DocumentListResponse)
def list_documents(
    settings: Annotated[Settings, Depends(get_settings)],
    tenant: Annotated[TenantContext, Depends(get_tenant)],
) -> DocumentListResponse:
    doc_dir = settings.tenant_documents_dir(tenant.tenant_id)
    docs: list[DocumentInfo] = []
    if doc_dir.exists() and doc_dir.is_dir():
        for file_path in sorted(doc_dir.iterdir()):
            if file_path.is_file() and file_path.suffix.lower() in {".txt", ".pdf"}:
                stat = file_path.stat()
                modified = datetime.datetime.fromtimestamp(stat.st_mtime, tz=datetime.UTC)
                docs.append(
                    DocumentInfo(
                        name=file_path.name,
                        path=file_path.name,
                        size_bytes=stat.st_size,
                        extension=file_path.suffix.lower(),
                        modified_at=modified.strftime("%Y-%m-%d %H:%M:%S UTC"),
                    )
                )
    return DocumentListResponse(documents=docs, total_count=len(docs), corpus_dir=str(doc_dir))


@router.post("/api/v1/documents/upload", response_model=DocumentUploadResponse)
async def upload_document(
    request: Request,
    settings: Annotated[Settings, Depends(get_settings)],
    service: Annotated[RagService, Depends(get_rag_service)],
    tenant: Annotated[TenantContext, Depends(get_tenant)],
) -> DocumentUploadResponse:
    form = await request.form(max_files=1, max_fields=0)
    try:
        file = form.get("file")
        if len(form) != 1 or not isinstance(file, UploadFile):
            raise HTTPException(
                status_code=400,
                detail="Upload exactly one document using the multipart field 'file'.",
            )
        return await _persist_document(file, settings, service, tenant)
    finally:
        await form.close()


async def _persist_document(
    file: UploadFile,
    settings: Settings,
    service: RagService,
    tenant: TenantContext,
) -> DocumentUploadResponse:
    filename = file.filename or ""
    if not _is_safe_filename(filename):
        raise HTTPException(status_code=400, detail="A safe document filename is required.")
    suffix = Path(filename).suffix.lower()
    if suffix not in {".txt", ".pdf"}:
        raise HTTPException(
            status_code=400,
            detail="Unsupported file format. Only .txt and .pdf files are accepted.",
        )

    content = bytearray()
    while len(content) <= settings.max_document_bytes:
        block = await file.read(min(64 * 1024, settings.max_document_bytes + 1 - len(content)))
        if not block:
            break
        content.extend(block)
    if len(content) > settings.max_document_bytes:
        raise HTTPException(
            status_code=413,
            detail=f"File exceeds maximum allowed size ({settings.max_document_bytes} bytes).",
        )

    if not content:
        raise HTTPException(status_code=400, detail="The uploaded document is empty.")
    if suffix == ".txt":
        try:
            bytes(content).decode("utf-8")
        except UnicodeDecodeError as exc:
            raise HTTPException(
                status_code=400, detail="TXT files must use UTF-8 encoding."
            ) from exc
    else:
        try:
            if not PdfReader(io.BytesIO(content), strict=True).pages:
                raise HTTPException(status_code=400, detail="The uploaded PDF has no pages.")
        except (PdfReadError, ValueError) as exc:
            raise HTTPException(
                status_code=400, detail="The uploaded PDF file is malformed."
            ) from exc

    with service.tenant_corpus_lock(tenant.tenant_id):
        doc_dir = settings.tenant_documents_dir(tenant.tenant_id)
        doc_dir.mkdir(parents=True, exist_ok=True)
        target_path = doc_dir / filename
        temporary_path = doc_dir / f".upload-{uuid.uuid4().hex}.tmp"
        try:
            temporary_path.write_bytes(content)
            os.replace(temporary_path, target_path)
        except OSError as exc:
            logger.error("Document upload failed (%s).", type(exc).__name__)
            raise HTTPException(status_code=500, detail="The document could not be saved.") from exc
        finally:
            if temporary_path.exists():
                temporary_path.unlink()

        service.invalidate_tenant(tenant.tenant_id)
    return DocumentUploadResponse(
        filename=filename,
        size_bytes=len(content),
        message=f"Document '{filename}' uploaded successfully.",
    )


@router.delete("/api/v1/documents/{filename}", response_model=DocumentDeleteResponse)
def delete_document(
    filename: str,
    settings: Annotated[Settings, Depends(get_settings)],
    service: Annotated[RagService, Depends(get_rag_service)],
    tenant: Annotated[TenantContext, Depends(get_tenant)],
) -> DocumentDeleteResponse:
    if not _is_safe_filename(filename) or Path(filename).suffix.lower() not in {".txt", ".pdf"}:
        raise HTTPException(status_code=400, detail="A safe document filename is required.")
    with service.tenant_corpus_lock(tenant.tenant_id):
        doc_dir = settings.tenant_documents_dir(tenant.tenant_id)
        raw_path = doc_dir / filename
        if raw_path.is_symlink():
            raise HTTPException(
                status_code=403, detail="Symbolic-link documents cannot be deleted."
            )
        target_path = raw_path.resolve()
        if target_path.parent != doc_dir.resolve():
            raise HTTPException(status_code=403, detail="Access denied.")
        if not target_path.is_file():
            raise HTTPException(status_code=404, detail="Document not found.")
        target_path.unlink()
        service.invalidate_tenant(tenant.tenant_id)
    return DocumentDeleteResponse(
        filename=filename,
        message=f"Document '{filename}' was deleted from the corpus.",
    )


@router.get("/api/v1/metrics", response_model=MetricsSummaryResponse)
def get_metrics_summary(
    service: Annotated[RagService, Depends(get_rag_service)],
    metrics: Annotated[MetricsStore, Depends(get_metrics_store)],
    tenant: Annotated[TenantContext, Depends(get_tenant)],
) -> MetricsSummaryResponse:
    snapshot = metrics.snapshot(tenant.tenant_id)
    return MetricsSummaryResponse(
        total_requests=snapshot["total_requests"],
        cache_hit_count=snapshot["cache_hits"],
        cache_miss_count=snapshot["cache_misses"],
        cache_hit_rate=round(snapshot["cache_hits"] / snapshot["total_requests"] * 100, 2)
        if snapshot["total_requests"]
        else 0.0,
        avg_latency_ms=round(snapshot["avg_latency_ms"], 2),
        p50_latency_ms=round(snapshot["p50_latency_ms"], 2),
        p95_latency_ms=round(snapshot["p95_latency_ms"], 2),
        total_cost_usd=round(snapshot["total_cost_usd"], 8),
        cheap_route_count=snapshot["cheap_routes"],
        strong_route_count=snapshot["strong_routes"],
        escalated_count=snapshot["escalated"],
        total_input_tokens=snapshot["input_tokens"],
        total_output_tokens=snapshot["output_tokens"],
        indexed_documents=service.document_count(tenant.tenant_id),
        indexed_chunks=service.chunk_count(tenant.tenant_id),
    )


@router.get("/api/v1/cache/stats", response_model=CacheStatsResponse)
def get_cache_stats(
    settings: Annotated[Settings, Depends(get_settings)],
    service: Annotated[RagService, Depends(get_rag_service)],
    metrics: Annotated[MetricsStore, Depends(get_metrics_store)],
    tenant: Annotated[TenantContext, Depends(get_tenant)],
) -> CacheStatsResponse:
    version = getattr(service.vector_store, "current_corpus_version", lambda _tenant: None)(
        tenant.tenant_id
    )
    snapshot = metrics.snapshot(tenant.tenant_id)
    count_entries = getattr(service.vector_store, "cache_entry_count", None)
    total_entries = count_entries(tenant.tenant_id, version) if version and count_entries else 0
    return CacheStatsResponse(
        enabled=settings.SEMANTIC_CACHE_ENABLED,
        threshold=settings.SEMANTIC_CACHE_THRESHOLD,
        ttl_seconds=settings.SEMANTIC_CACHE_TTL_SECONDS,
        total_entries=total_entries,
        hits=snapshot["cache_hits"],
        misses=snapshot["cache_misses"],
        corpus_version=version or "none",
    )


@router.post("/api/v1/cache/invalidate")
def invalidate_cache(
    service: Annotated[RagService, Depends(get_rag_service)],
    tenant: Annotated[TenantContext, Depends(get_tenant)],
) -> dict[str, str]:
    service.invalidate_cache(tenant.tenant_id)
    return {"status": "success", "message": "Tenant semantic cache invalidated."}
