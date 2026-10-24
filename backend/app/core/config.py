"""Application configuration module using Pydantic Settings.

Reads environment variables from system environment and `.env` file,
providing strictly typed and validated settings across the application.
"""

import hashlib
from functools import lru_cache
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Central configuration class for the RAG engine."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # --- Application Core ---
    APP_NAME: str = Field(
        default="Semantic Cache & Cost-Aware RAG Engine",
        description="Public display name of the application",
    )
    APP_ENV: Literal["development", "production", "testing"] = Field(
        default="development",
        description="Execution environment mode",
    )
    LOG_LEVEL: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = Field(
        default="INFO",
        description="Global log verbosity level",
    )
    API_HOST: str = Field(default="0.0.0.0", description="Host address to bind HTTP server")
    API_PORT: int = Field(
        default=8000, description="Port number to bind HTTP server", ge=1, le=65535
    )
    DEBUG: bool = Field(default=False, description="Enable debug diagnostics and stack traces")

    # --- Document Corpus & Chunking ---
    CORPUS_DIR: str = Field(default="data/documents", description="Directory holding raw documents")
    CORPUS_VERSION: str = Field(
        default="v1.0.0", description="Corpus version identifier for cache invalidation"
    )
    CHUNK_SIZE: int = Field(default=500, description="Target token/character count per chunk", ge=1)
    CHUNK_OVERLAP: int = Field(
        default=50, description="Overlap token/character count between contiguous chunks", ge=0
    )

    # --- Embedding Model ---
    EMBEDDING_MODEL_NAME: str = Field(
        default="sentence-transformers/all-MiniLM-L6-v2",
        description="HuggingFace model ID for dense vector generation",
    )
    EMBEDDING_DIMENSION: int = Field(
        default=384, description="Vector dimension size produced by the embedding model", ge=1
    )
    EMBEDDING_DEVICE: Literal["cpu", "cuda"] = Field(
        default="cpu", description="Compute device for embeddings"
    )

    # --- Vector Store (Qdrant) ---
    QDRANT_USE_LOCAL_STORAGE: bool = Field(
        default=True,
        description="Whether to use embedded local disk storage or external Qdrant server",
    )
    QDRANT_LOCAL_PATH: str = Field(
        default="data/qdrant_storage",
        description="Directory for embedded Qdrant database",
    )
    QDRANT_HOST: str = Field(default="localhost", description="Qdrant server hostname")
    QDRANT_PORT: int = Field(
        default=6333, description="Qdrant server gRPC/HTTP port", ge=1, le=65535
    )
    QDRANT_URL: str | None = Field(default=None, description="Remote Qdrant HTTP(S) URL")
    QDRANT_API_KEY: str | None = Field(
        default=None, description="Optional API key for Qdrant Cloud or secured instance"
    )
    QDRANT_COLLECTION_DOCS: str = Field(
        default="rag_documents", description="Collection name for document chunks"
    )
    QDRANT_COLLECTION_CACHE: str = Field(
        default="rag_semantic_cache", description="Collection name for semantic cache"
    )

    # --- Request Logging & Metrics (SQLite) ---
    DATABASE_URL: str = Field(
        default="sqlite:///./data/metrics.db",
        description="Database connection string for request logs and performance metrics",
    )
    LOG_SENSITIVE_QUERIES: bool = Field(
        default=False,
        description="Deprecated compatibility setting; query text is never written to metrics",
    )

    # --- Semantic Query Cache ---
    SEMANTIC_CACHE_ENABLED: bool = Field(
        default=True, description="Master toggle for semantic query caching"
    )
    SEMANTIC_CACHE_THRESHOLD: float = Field(
        default=0.90,
        description="Cosine similarity threshold for a cache hit (0.0 to 1.0)",
    )
    SEMANTIC_CACHE_TTL_SECONDS: int = Field(
        default=86400,
        description="Time-to-live in seconds before cached query answers expire",
        ge=1,
        le=31_536_000,
    )

    # --- LLM Providers & Cost Routing ---
    LLM_PROVIDER: Literal["mock", "ollama", "groq", "openai", "gemini"] = Field(
        default="mock",
        description="Active LLM provider backend",
    )
    CHEAP_MODEL_NAME: str = Field(
        default="mock-cheap", description="Name of the cheaper, faster model"
    )
    STRONG_MODEL_NAME: str = Field(
        default="mock-strong", description="Name of the stronger reasoning model"
    )
    OPENAI_API_KEY: str | None = Field(default=None, description="OpenAI API secret key")
    GROQ_API_KEY: str | None = Field(default=None, description="Groq API secret key")
    GEMINI_API_KEY: str | None = Field(default=None, description="Google Gemini API secret key")
    OLLAMA_BASE_URL: str = Field(default="http://127.0.0.1:11434")

    # Pricing in USD per 1 Million tokens
    CHEAP_MODEL_INPUT_PRICE_PER_1M: float = Field(
        default=0.15, description="Input price in USD per 1M tokens", ge=0
    )
    CHEAP_MODEL_OUTPUT_PRICE_PER_1M: float = Field(
        default=0.60, description="Output price in USD per 1M tokens", ge=0
    )
    STRONG_MODEL_INPUT_PRICE_PER_1M: float = Field(
        default=2.50, description="Input price in USD per 1M tokens", ge=0
    )
    STRONG_MODEL_OUTPUT_PRICE_PER_1M: float = Field(
        default=10.00, description="Output price in USD per 1M tokens", ge=0
    )

    # --- Confidence Escalation ---
    ESCALATION_ENABLED: bool = Field(
        default=True, description="Enable escalation from cheap to strong model"
    )
    MAX_ESCALATION_RETRIES: int = Field(
        default=1, description="Maximum escalation attempts per query", ge=0, le=5
    )
    CONFIDENCE_THRESHOLD: float = Field(
        default=0.70, description="Minimum confidence score required to accept answer"
    )

    # --- Security & Multi-tenancy ---
    DEFAULT_TENANT_ID: str = Field(
        default="tenant-default", description="Development tenant identifier"
    )
    REQUIRE_TENANT_AUTH: bool = Field(
        default=False, description="Require signed tenant bearer tokens"
    )
    AUTH_SECRET_KEY: str | None = Field(default=None, description="HS256 JWT signing secret")
    AUTH_ISSUER: str = Field(default="semantic-cache-rag")
    AUTH_AUDIENCE: str = Field(default="semantic-cache-rag-api")
    AUTH_MAX_TOKEN_TTL_SECONDS: int = Field(default=86400, ge=60, le=604800)
    CORS_ALLOWED_ORIGINS: list[str] = Field(
        default_factory=lambda: ["http://localhost:5173", "http://127.0.0.1:5173"]
    )
    RATE_LIMIT_REQUESTS_PER_MINUTE: int = Field(default=120, ge=1, le=10000)
    MAX_METRIC_RECORDS: int = Field(default=10000, ge=100, le=1000000)
    PROVIDER_TIMEOUT_SECONDS: float = Field(default=20.0, gt=0, le=300)
    PROVIDER_RETRY_COUNT: int = Field(default=2, ge=0, le=5)

    # --- Backward compatibility & dynamic overrides for main.py & tests ---
    documents_dir_override: Path | None = Field(default=None, alias="documents_dir")
    qdrant_path_override: Path | None = Field(default=None, alias="qdrant_path")
    qdrant_collection_override: str | None = Field(default=None, alias="qdrant_collection")
    embedding_model_override: str | None = Field(default=None, alias="embedding_model")
    chunk_size_tokens_override: int | None = Field(default=None, alias="chunk_size_tokens")
    chunk_overlap_tokens_override: int | None = Field(default=None, alias="chunk_overlap_tokens")
    max_document_bytes: int = Field(default=10 * 1024 * 1024, ge=1, le=100 * 1024 * 1024)
    min_retrieval_score: float = Field(default=0.2, ge=0, le=1)
    top_k: int = Field(default=5, ge=1, le=20)

    @property
    def documents_dir(self) -> Path:
        return self.documents_dir_override or Path(self.CORPUS_DIR)

    @property
    def qdrant_path(self) -> Path:
        return self.qdrant_path_override or Path(self.QDRANT_LOCAL_PATH)

    @property
    def qdrant_url(self) -> str:
        return self.QDRANT_URL or f"http://{self.QDRANT_HOST}:{self.QDRANT_PORT}"

    @property
    def metrics_db_path(self) -> Path:
        prefix = "sqlite:///"
        if not self.DATABASE_URL.startswith(prefix):
            raise ValueError("Only SQLite DATABASE_URL values are supported.")
        path = self.DATABASE_URL[len(prefix) :]
        return Path(path)

    def tenant_documents_dir(self, tenant_id: str) -> Path:
        if not self.REQUIRE_TENANT_AUTH and tenant_id == self.DEFAULT_TENANT_ID:
            return self.documents_dir
        tenant_key = hashlib.sha256(tenant_id.encode("utf-8")).hexdigest()[:32]
        return self.documents_dir / "_tenants" / tenant_key

    @property
    def qdrant_collection(self) -> str:
        return self.qdrant_collection_override or self.QDRANT_COLLECTION_DOCS

    @property
    def embedding_model(self) -> str:
        return self.embedding_model_override or self.EMBEDDING_MODEL_NAME

    @property
    def chunk_size_tokens(self) -> int:
        return (
            self.chunk_size_tokens_override
            if self.chunk_size_tokens_override is not None
            else self.CHUNK_SIZE
        )

    @property
    def chunk_overlap_tokens(self) -> int:
        return (
            self.chunk_overlap_tokens_override
            if self.chunk_overlap_tokens_override is not None
            else self.CHUNK_OVERLAP
        )

    @field_validator("SEMANTIC_CACHE_THRESHOLD", "CONFIDENCE_THRESHOLD")
    @classmethod
    def validate_thresholds(cls, value: float) -> float:
        """Ensure similarity and confidence thresholds fall within [0.0, 1.0]."""
        if not 0.0 <= value <= 1.0:
            raise ValueError(f"Threshold must be between 0.0 and 1.0, got {value}")
        return value

    @field_validator("CORS_ALLOWED_ORIGINS")
    @classmethod
    def validate_cors_origins(cls, origins: list[str]) -> list[str]:
        for origin in origins:
            parsed = urlsplit(origin)
            if (
                origin == "*"
                or parsed.scheme not in {"http", "https"}
                or not parsed.netloc
                or parsed.path
                or parsed.query
                or parsed.fragment
                or "*" in parsed.netloc
                or parsed.username
                or parsed.password
            ):
                raise ValueError(
                    "CORS origins must be explicit HTTP(S) origins without paths or credentials."
                )
        return origins

    @field_validator("DATABASE_URL")
    @classmethod
    def validate_metrics_database_url(cls, value: str) -> str:
        if not value.startswith("sqlite:///") or value.endswith(":memory:"):
            raise ValueError("DATABASE_URL must point to a file-backed SQLite database.")
        return value

    @field_validator("AUTH_ISSUER", "AUTH_AUDIENCE")
    @classmethod
    def validate_auth_identifier(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Authentication issuer and audience must not be blank.")
        return value

    @field_validator("OLLAMA_BASE_URL")
    @classmethod
    def validate_ollama_url(cls, value: str) -> str:
        parsed = urlsplit(value)
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.netloc
            or parsed.query
            or parsed.fragment
            or parsed.username
            or parsed.password
        ):
            raise ValueError("OLLAMA_BASE_URL must be a valid HTTP(S) URL without credentials.")
        return value.rstrip("/")

    @field_validator("QDRANT_URL")
    @classmethod
    def validate_qdrant_url(cls, value: str | None) -> str | None:
        if not value:
            return None
        parsed = urlsplit(value)
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.netloc
            or parsed.path not in {"", "/"}
            or parsed.query
            or parsed.fragment
            or parsed.username
            or parsed.password
        ):
            raise ValueError(
                "QDRANT_URL must be an HTTP(S) origin without credentials or query data."
            )
        return value.rstrip("/")

    @field_validator("DEFAULT_TENANT_ID")
    @classmethod
    def validate_default_tenant(cls, value: str) -> str:
        if not value or len(value) > 64 or not value[0].isascii() or not value[0].isalnum():
            raise ValueError(
                "DEFAULT_TENANT_ID must be a safe identifier of at most 64 characters."
            )
        if not all(
            character.isascii() and (character.isalnum() or character in "._-")
            for character in value
        ):
            raise ValueError("DEFAULT_TENANT_ID contains an invalid character.")
        return value

    @model_validator(mode="after")
    def validate_chunk_settings(self) -> "Settings":
        """Verify chunk overlap is strictly smaller than chunk size."""
        size = self.chunk_size_tokens
        overlap = self.chunk_overlap_tokens
        if overlap >= size:
            raise ValueError(
                f"CHUNK_OVERLAP ({overlap}) must be strictly less than CHUNK_SIZE ({size})"
            )
        if self.APP_ENV == "production":
            if self.DEBUG:
                raise ValueError("DEBUG must be disabled in production.")
            if not self.REQUIRE_TENANT_AUTH:
                raise ValueError("REQUIRE_TENANT_AUTH must be enabled in production.")
            if not self.AUTH_SECRET_KEY or len(self.AUTH_SECRET_KEY) < 32:
                raise ValueError(
                    "AUTH_SECRET_KEY must contain at least 32 characters in production."
                )
            if self.AUTH_SECRET_KEY.lower().startswith("dev-"):
                raise ValueError("A development AUTH_SECRET_KEY cannot be used in production.")
            if (
                self.QDRANT_USE_LOCAL_STORAGE
                or not self.QDRANT_API_KEY
                or not self.QDRANT_URL
                or not self.QDRANT_URL.startswith("https://")
            ):
                raise ValueError("Production requires HTTPS remote Qdrant storage with an API key.")
            if any(
                urlsplit(origin).hostname in {"localhost", "127.0.0.1", "::1"}
                for origin in self.CORS_ALLOWED_ORIGINS
            ):
                raise ValueError("Production CORS origins cannot point to localhost.")
            ollama = urlsplit(self.OLLAMA_BASE_URL)
            if (
                self.LLM_PROVIDER == "ollama"
                and ollama.scheme != "https"
                and ollama.hostname not in {"localhost", "127.0.0.1", "::1"}
            ):
                raise ValueError(
                    "Production Ollama endpoints must use HTTPS unless loopback-local."
                )
        if self.REQUIRE_TENANT_AUTH and (
            not self.AUTH_SECRET_KEY or len(self.AUTH_SECRET_KEY) < 32
        ):
            raise ValueError(
                "AUTH_SECRET_KEY must contain at least 32 characters when auth is enabled."
            )
        if any(origin == "*" for origin in self.CORS_ALLOWED_ORIGINS):
            raise ValueError("CORS_ALLOWED_ORIGINS cannot contain a wildcard origin.")
        for origin in self.CORS_ALLOWED_ORIGINS:
            if not origin.startswith(("http://", "https://")):
                raise ValueError("Each CORS origin must use http:// or https://.")
        return self


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return a cached singleton instance of application settings.

    Uses functools.lru_cache so the configuration file is parsed only once,
    avoiding repeated disk reads on high-throughput API endpoints.
    """
    return Settings()
