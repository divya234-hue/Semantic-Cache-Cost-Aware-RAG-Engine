import sqlite3
import threading
from pathlib import Path
from typing import TypedDict


class MetricsSnapshot(TypedDict):
    total_requests: int
    cache_hits: int
    cache_misses: int
    avg_latency_ms: float
    p50_latency_ms: float
    p95_latency_ms: float
    total_cost_usd: float
    cheap_routes: int
    strong_routes: int
    escalated: int
    input_tokens: int
    output_tokens: int


class MetricsStore:
    def __init__(self, database_path: Path, max_records: int) -> None:
        database_path.parent.mkdir(parents=True, exist_ok=True)
        self._connection = sqlite3.connect(database_path, check_same_thread=False, timeout=30)
        self._connection.row_factory = sqlite3.Row
        self._lock = threading.RLock()
        self.max_records = max_records
        with self._lock:
            self._connection.execute("PRAGMA busy_timeout = 30000")
            self._connection.execute(
                """
                CREATE TABLE IF NOT EXISTS request_metrics (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    tenant_id TEXT NOT NULL,
                    latency_ms REAL NOT NULL,
                    cache_hit INTEGER NOT NULL,
                    route TEXT NOT NULL,
                    escalated INTEGER NOT NULL,
                    cost_usd REAL NOT NULL,
                    input_tokens INTEGER NOT NULL DEFAULT 0,
                    output_tokens INTEGER NOT NULL DEFAULT 0
                )
                """
            )
            columns = {
                row["name"]
                for row in self._connection.execute("PRAGMA table_info(request_metrics)")
            }
            for column in ("input_tokens", "output_tokens"):
                if column not in columns:
                    self._connection.execute(
                        f"ALTER TABLE request_metrics ADD COLUMN {column} INTEGER NOT NULL DEFAULT 0"
                    )
            self._connection.execute(
                "CREATE INDEX IF NOT EXISTS request_metrics_tenant_id ON request_metrics(tenant_id, id)"
            )
            self._connection.commit()

    def record(
        self,
        tenant_id: str,
        latency_ms: float,
        cache_hit: bool,
        route: str,
        escalated: bool,
        cost_usd: float,
        input_tokens: int,
        output_tokens: int,
    ) -> None:
        with self._lock, self._connection:
            self._connection.execute(
                """
                INSERT INTO request_metrics
                    (tenant_id, latency_ms, cache_hit, route, escalated, cost_usd,
                     input_tokens, output_tokens)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    tenant_id,
                    latency_ms,
                    int(cache_hit),
                    route,
                    int(escalated),
                    cost_usd,
                    input_tokens,
                    output_tokens,
                ),
            )
            self._connection.execute(
                """
                DELETE FROM request_metrics
                WHERE id NOT IN (
                    SELECT id FROM request_metrics ORDER BY id DESC LIMIT ?
                )
                """,
                (self.max_records,),
            )

    def snapshot(self, tenant_id: str) -> MetricsSnapshot:
        with self._lock:
            rows = self._connection.execute(
                """
                SELECT latency_ms, cache_hit, route, escalated, cost_usd,
                       input_tokens, output_tokens
                FROM request_metrics WHERE tenant_id = ? ORDER BY id DESC LIMIT ?
                """,
                (tenant_id, self.max_records),
            ).fetchall()
        latencies = sorted(float(row["latency_ms"]) for row in rows)
        total = len(rows)
        hits = sum(int(row["cache_hit"]) for row in rows)
        return {
            "total_requests": total,
            "cache_hits": hits,
            "cache_misses": total - hits,
            "avg_latency_ms": sum(latencies) / total if total else 0.0,
            "p50_latency_ms": latencies[int((total - 1) * 0.50)] if total else 0.0,
            "p95_latency_ms": latencies[int((total - 1) * 0.95)] if total else 0.0,
            "total_cost_usd": sum(float(row["cost_usd"]) for row in rows),
            "cheap_routes": sum(row["route"] == "cheap" for row in rows),
            "strong_routes": sum(row["route"] == "strong" for row in rows),
            "escalated": sum(int(row["escalated"]) for row in rows),
            "input_tokens": sum(int(row["input_tokens"]) for row in rows),
            "output_tokens": sum(int(row["output_tokens"]) for row in rows),
        }

    def close(self) -> None:
        with self._lock:
            self._connection.close()
