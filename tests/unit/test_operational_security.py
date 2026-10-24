import sqlite3
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi import HTTPException

from backend.app.core.security import TenantRateLimiter
from backend.app.repositories.qdrant_vector_store import QdrantVectorStore
from backend.app.services.metrics_store import MetricsStore


def test_rate_limit_is_bounded_by_tenant_window() -> None:
    limiter = TenantRateLimiter(requests_per_minute=1)
    limiter.check("tenant-a")
    with pytest.raises(HTTPException) as error:
        limiter.check("tenant-a")
    assert error.value.status_code == 429
    limiter.check("tenant-b")


def test_metrics_store_is_thread_safe_tenant_scoped_and_bounded(tmp_path) -> None:
    store = MetricsStore(tmp_path / "metrics.sqlite3", max_records=100)
    try:

        def write(index: int) -> None:
            store.record(
                "tenant-a" if index % 2 == 0 else "tenant-b",
                float(index),
                index % 3 == 0,
                "cheap",
                False,
                0.001,
                3,
                2,
            )

        with ThreadPoolExecutor(max_workers=8) as executor:
            list(executor.map(write, range(140)))

        tenant_a = store.snapshot("tenant-a")
        tenant_b = store.snapshot("tenant-b")
        assert tenant_a["total_requests"] + tenant_b["total_requests"] == 100
        assert tenant_a["input_tokens"] == tenant_a["total_requests"] * 3
        assert tenant_b["output_tokens"] == tenant_b["total_requests"] * 2
    finally:
        store.close()


def test_metrics_store_migrates_legacy_schema_without_losing_rows(tmp_path) -> None:
    database_path = tmp_path / "legacy-metrics.sqlite3"
    connection = sqlite3.connect(database_path)
    connection.execute(
        """
        CREATE TABLE request_metrics (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            tenant_id TEXT NOT NULL,
            latency_ms REAL NOT NULL,
            cache_hit INTEGER NOT NULL,
            route TEXT NOT NULL,
            escalated INTEGER NOT NULL,
            cost_usd REAL NOT NULL
        )
        """
    )
    connection.execute(
        """INSERT INTO request_metrics
           (tenant_id, latency_ms, cache_hit, route, escalated, cost_usd)
           VALUES (?, ?, ?, ?, ?, ?)""",
        ("tenant-a", 12.5, 0, "cheap", 0, 0.001),
    )
    connection.commit()
    connection.close()

    store = MetricsStore(database_path, max_records=100)
    try:
        legacy_snapshot = store.snapshot("tenant-a")
        assert legacy_snapshot["total_requests"] == 1
        assert legacy_snapshot["input_tokens"] == 0
        assert legacy_snapshot["output_tokens"] == 0

        store.record("tenant-a", 4.0, True, "cache", False, 0.0, 0, 0)
        updated_snapshot = store.snapshot("tenant-a")
        assert updated_snapshot["total_requests"] == 2
        assert updated_snapshot["cache_hits"] == 1
    finally:
        store.close()

def test_qdrant_cache_enforces_tenant_and_ttl(tmp_path) -> None:
    store = QdrantVectorStore(
        path=str(tmp_path / "qdrant"),
        collection_name="cache_expiry_test",
        vector_size=2,
    )
    try:
        response = {
            "status": "supported",
            "answer": "The answer.",
            "citations": [],
            "provider": "local-extractive",
        }
        store.upsert_cache([1.0, 0.0], response, "tenant-a", "version-a", ttl_seconds=60)
        assert store.search_cache([1.0, 0.0], "tenant-a", "version-a", 0.9) is not None
        assert store.search_cache([1.0, 0.0], "tenant-b", "version-a", 0.9) is None

        store.upsert_cache([1.0, 0.0], response, "tenant-a", "version-a", ttl_seconds=0)
        assert store.search_cache([1.0, 0.0], "tenant-a", "version-a", 0.9) is None
        store.invalidate_cache("tenant-a")
        assert store.cache_entry_count("tenant-a", "version-a") == 0
    finally:
        store.client.close()
