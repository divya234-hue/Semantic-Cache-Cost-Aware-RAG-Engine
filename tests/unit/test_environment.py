"""Unit tests for Phase 0 environment and configuration verification."""

from pathlib import Path

import pytest
from pydantic import ValidationError

from backend.app.core.config import Settings


def test_settings_load_defaults():
    """Verify that settings can be loaded cleanly with valid types."""
    settings = Settings(_env_file=None)
    assert settings.APP_NAME == "Semantic Cache & Cost-Aware RAG Engine"
    assert settings.SEMANTIC_CACHE_ENABLED is True
    assert 0.0 <= settings.SEMANTIC_CACHE_THRESHOLD <= 1.0
    assert settings.CHUNK_OVERLAP < settings.CHUNK_SIZE
    assert settings.EMBEDDING_DIMENSION > 0


def test_settings_threshold_validation():
    """Verify that semantic cache threshold validator enforces 0.0 to 1.0 range."""
    with pytest.raises(ValidationError):
        Settings(_env_file=None, SEMANTIC_CACHE_THRESHOLD=1.5)

    with pytest.raises(ValidationError):
        Settings(_env_file=None, SEMANTIC_CACHE_THRESHOLD=-0.1)


def test_chunk_overlap_validation():
    """Verify that chunk overlap validator rejects overlap >= chunk size."""
    with pytest.raises(ValidationError):
        Settings(_env_file=None, CHUNK_SIZE=500, CHUNK_OVERLAP=500)

    with pytest.raises(ValidationError):
        Settings(_env_file=None, CHUNK_SIZE=300, CHUNK_OVERLAP=400)


def test_production_requires_auth_and_remote_qdrant() -> None:
    with pytest.raises(ValidationError):
        Settings(_env_file=None, APP_ENV="production")

    settings = Settings(
        _env_file=None,
        APP_ENV="production",
        REQUIRE_TENANT_AUTH=True,
        AUTH_SECRET_KEY="a" * 40,
        QDRANT_USE_LOCAL_STORAGE=False,
        QDRANT_URL="https://qdrant.example.test",
        QDRANT_API_KEY="test-key-not-used-for-network",
        CORS_ALLOWED_ORIGINS=["https://app.example.test"],
    )
    assert settings.REQUIRE_TENANT_AUTH is True


def test_production_rejects_debug_and_remote_http_ollama() -> None:
    production = {
        "APP_ENV": "production",
        "REQUIRE_TENANT_AUTH": True,
        "AUTH_SECRET_KEY": "a" * 40,
        "QDRANT_USE_LOCAL_STORAGE": False,
        "QDRANT_URL": "https://qdrant.example.test",
        "QDRANT_API_KEY": "test-key-not-used-for-network",
        "CORS_ALLOWED_ORIGINS": ["https://app.example.test"],
    }
    with pytest.raises(ValidationError):
        Settings(_env_file=None, **production, DEBUG=True)

    with pytest.raises(ValidationError):
        Settings(
            _env_file=None,
            **production,
            LLM_PROVIDER="ollama",
            OLLAMA_BASE_URL="http://ollama.internal:11434",
        )


def test_cors_wildcard_and_non_sqlite_metrics_database_are_rejected() -> None:
    with pytest.raises(ValidationError):
        Settings(_env_file=None, CORS_ALLOWED_ORIGINS=["*"])

    with pytest.raises(ValidationError):
        Settings(_env_file=None, DATABASE_URL="postgresql://localhost/metrics")


def test_project_directories_exist():
    """Verify required top-level and backend folders exist."""
    root = Path(__file__).resolve().parent.parent.parent
    expected = [
        "backend/app/api",
        "backend/app/core",
        "backend/app/models",
        "backend/app/repositories",
        "backend/app/schemas",
        "backend/app/services",
        "data/documents",
        "evaluation/datasets",
        "evaluation/results",
        "tests/unit",
    ]
    for rel_path in expected:
        assert (root / rel_path).is_dir(), f"Expected directory {rel_path} does not exist"
