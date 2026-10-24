from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class AskRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    query: str = Field(min_length=4, max_length=2000)
    top_k: int | None = Field(default=None, ge=1, le=20)

    @field_validator("query")
    @classmethod
    def query_must_contain_non_whitespace(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("query must not be blank")
        return value


class Citation(BaseModel):
    document_id: str
    chunk_id: str
    source_path: str
    retrieval_score: float


class AskResponse(BaseModel):
    status: Literal["supported", "insufficient_evidence"]
    answer: str
    citations: list[Citation]
    provider: str
    model: str | None = None
    cache_hit: bool = False
    route: Literal["cheap", "strong"] = "cheap"
    escalated: bool = False
    cost_usd: float = Field(default=0.0, ge=0)
    input_tokens: int = Field(default=0, ge=0)
    output_tokens: int = Field(default=0, ge=0)


class IngestResponse(BaseModel):
    documents_ingested: int
    chunks_indexed: int
    corpus_version: str


class HealthResponse(BaseModel):
    status: Literal["ok", "ready"]


class DocumentInfo(BaseModel):
    name: str
    path: str
    size_bytes: int
    extension: str
    modified_at: str


class DocumentListResponse(BaseModel):
    documents: list[DocumentInfo]
    total_count: int
    corpus_dir: str


class DocumentUploadResponse(BaseModel):
    filename: str
    size_bytes: int
    message: str


class DocumentDeleteResponse(BaseModel):
    filename: str
    message: str


class SystemSettingsResponse(BaseModel):
    app_name: str
    app_env: str
    log_level: str
    corpus_dir: str
    corpus_version: str
    embedding_model: str
    embedding_dimension: int
    qdrant_local_path: str
    qdrant_collection: str
    semantic_cache_enabled: bool
    cache_threshold: float
    cache_ttl_seconds: int
    llm_provider: str
    cheap_model: str
    strong_model: str
    escalation_enabled: bool
    cheap_input_price: float
    cheap_output_price: float
    strong_input_price: float
    strong_output_price: float
    tenant_auth_enabled: bool


class MetricsSummaryResponse(BaseModel):
    total_requests: int
    cache_hit_count: int
    cache_miss_count: int
    cache_hit_rate: float
    avg_latency_ms: float
    p50_latency_ms: float
    p95_latency_ms: float
    total_cost_usd: float
    cheap_route_count: int
    strong_route_count: int
    escalated_count: int
    total_input_tokens: int
    total_output_tokens: int
    indexed_documents: int
    indexed_chunks: int


class CacheStatsResponse(BaseModel):
    enabled: bool
    threshold: float
    ttl_seconds: int
    total_entries: int
    hits: int
    misses: int
    corpus_version: str
