import hashlib
import time
import uuid
from collections.abc import Sequence
from typing import Any

from qdrant_client import QdrantClient, models

from backend.app.models.domain import DocumentChunk, RetrievedChunk


class QdrantVectorStore:
    def __init__(
        self,
        path: str | None,
        collection_name: str,
        vector_size: int,
        url: str | None = None,
        api_key: str | None = None,
        cache_collection_name: str | None = None,
    ) -> None:
        if url:
            self.client = QdrantClient(url=url, api_key=api_key)
        elif path:
            self.client = QdrantClient(path=path)
        else:
            raise ValueError("Either a local Qdrant path or a remote Qdrant URL is required.")
        self.collection_name = collection_name
        self.vector_size = vector_size
        self.cache_collection_name = cache_collection_name or f"{collection_name}_cache"
        self._current_corpus_versions: dict[str, str] = {}

    @property
    def _current_corpus_version(self) -> str | None:
        return self.current_corpus_version("tenant-default")

    def upsert_corpus(
        self,
        chunks: Sequence[DocumentChunk],
        vectors: Sequence[Sequence[float]],
        corpus_version: str,
        tenant_id: str = "tenant-default",
    ) -> None:
        if len(chunks) != len(vectors):
            raise ValueError("Each document chunk must have exactly one embedding.")
        if not self.client.collection_exists(self.collection_name):
            self.client.create_collection(
                collection_name=self.collection_name,
                vectors_config=models.VectorParams(
                    size=self.vector_size,
                    distance=models.Distance.COSINE,
                ),
            )

        points = [
            models.PointStruct(
                id=str(uuid.uuid5(uuid.NAMESPACE_URL, f"{tenant_id}:{chunk.chunk_id}")),
                vector=list(vector),
                payload={
                    "document_id": chunk.document_id,
                    "chunk_id": chunk.chunk_id,
                    "source_path": chunk.source_path,
                    "corpus_version": chunk.corpus_version,
                    "text": chunk.text,
                    "token_count": chunk.token_count,
                    "tenant_id": tenant_id,
                },
            )
            for chunk, vector in zip(chunks, vectors, strict=True)
        ]
        self.client.upsert(
            collection_name=self.collection_name,
            points=points,
            wait=True,
        )
        self.client.delete(
            collection_name=self.collection_name,
            points_selector=models.Filter(
                must=[
                    models.FieldCondition(
                        key="tenant_id",
                        match=models.MatchValue(value=tenant_id),
                    )
                ],
                must_not=[
                    models.FieldCondition(
                        key="corpus_version",
                        match=models.MatchValue(value=corpus_version),
                    )
                ],
            ),
            wait=True,
        )
        self._current_corpus_versions[tenant_id] = corpus_version
        self.invalidate_cache(tenant_id)

    def search(
        self,
        vector: Sequence[float],
        limit: int,
        tenant_id: str = "tenant-default",
        corpus_version: str | None = None,
    ) -> list[RetrievedChunk]:
        version = corpus_version or self.current_corpus_version(tenant_id)
        if not version or not self.client.collection_exists(self.collection_name):
            return []
        result = self.client.query_points(
            collection_name=self.collection_name,
            query=list(vector),
            query_filter=models.Filter(
                must=[
                    models.FieldCondition(
                        key="corpus_version",
                        match=models.MatchValue(value=version),
                    ),
                    models.FieldCondition(
                        key="tenant_id",
                        match=models.MatchValue(value=tenant_id),
                    ),
                ]
            ),
            limit=limit,
            with_payload=True,
        )
        retrieved: list[RetrievedChunk] = []
        for point in result.points:
            payload = point.payload
            if not payload:
                continue
            retrieved.append(
                RetrievedChunk(
                    chunk=DocumentChunk(
                        document_id=str(payload["document_id"]),
                        chunk_id=str(payload["chunk_id"]),
                        source_path=str(payload["source_path"]),
                        corpus_version=str(payload["corpus_version"]),
                        text=str(payload["text"]),
                        token_count=int(payload["token_count"]),
                    ),
                    score=float(point.score),
                )
            )
        return retrieved

    def current_corpus_version(self, tenant_id: str) -> str | None:
        version = self._current_corpus_versions.get(tenant_id)
        if version or not self.client.collection_exists(self.collection_name):
            return version
        records, _ = self.client.scroll(
            collection_name=self.collection_name,
            scroll_filter=models.Filter(
                must=[
                    models.FieldCondition(
                        key="tenant_id",
                        match=models.MatchValue(value=tenant_id),
                    )
                ]
            ),
            limit=1,
            with_payload=["corpus_version"],
        )
        if records and records[0].payload:
            version = str(records[0].payload["corpus_version"])
            self._current_corpus_versions[tenant_id] = version
        return version

    def search_cache(
        self,
        vector: Sequence[float],
        tenant_id: str,
        corpus_version: str,
        threshold: float,
    ) -> tuple[dict[str, Any], float] | None:
        if not self.client.collection_exists(self.cache_collection_name):
            return None
        result = self.client.query_points(
            collection_name=self.cache_collection_name,
            query=list(vector),
            query_filter=models.Filter(
                must=[
                    models.FieldCondition(
                        key="tenant_id", match=models.MatchValue(value=tenant_id)
                    ),
                    models.FieldCondition(
                        key="corpus_version",
                        match=models.MatchValue(value=corpus_version),
                    ),
                    models.FieldCondition(
                        key="expires_at",
                        range=models.Range(gt=time.time()),
                    ),
                ]
            ),
            limit=1,
            with_payload=True,
        )
        if not result.points or result.points[0].score is None:
            return None
        point = result.points[0]
        if point.score < threshold or not isinstance(point.payload, dict):
            return None
        payload = point.payload
        response = payload.get("response")
        if not isinstance(response, dict):
            return None
        return response, float(point.score)

    def upsert_cache(
        self,
        vector: Sequence[float],
        response: dict[str, Any],
        tenant_id: str,
        corpus_version: str,
        ttl_seconds: int,
    ) -> None:
        current_time = time.time()
        if not self.client.collection_exists(self.cache_collection_name):
            self.client.create_collection(
                collection_name=self.cache_collection_name,
                vectors_config=models.VectorParams(
                    size=self.vector_size,
                    distance=models.Distance.COSINE,
                ),
            )
        else:
            self.client.delete(
                collection_name=self.cache_collection_name,
                points_selector=models.Filter(
                    must=[
                        models.FieldCondition(
                            key="tenant_id",
                            match=models.MatchValue(value=tenant_id),
                        ),
                        models.FieldCondition(
                            key="expires_at",
                            range=models.Range(lt=current_time),
                        ),
                    ]
                ),
                wait=True,
            )
        vector_fingerprint = hashlib.sha256(
            ",".join(format(value, ".9g") for value in vector).encode("ascii")
        ).hexdigest()
        self.client.upsert(
            collection_name=self.cache_collection_name,
            points=[
                models.PointStruct(
                    id=str(
                        uuid.uuid5(
                            uuid.NAMESPACE_URL,
                            f"{tenant_id}:{corpus_version}:{vector_fingerprint}",
                        )
                    ),
                    vector=list(vector),
                    payload={
                        "tenant_id": tenant_id,
                        "corpus_version": corpus_version,
                        "created_at": current_time,
                        "expires_at": current_time + ttl_seconds,
                        "response": response,
                    },
                )
            ],
            wait=True,
        )

    def invalidate_cache(self, tenant_id: str, corpus_version: str | None = None) -> None:
        if not self.client.collection_exists(self.cache_collection_name):
            return
        conditions = [
            models.FieldCondition(key="tenant_id", match=models.MatchValue(value=tenant_id))
        ]
        if corpus_version is not None:
            conditions.append(
                models.FieldCondition(
                    key="corpus_version",
                    match=models.MatchValue(value=corpus_version),
                )
            )
        self.client.delete(
            collection_name=self.cache_collection_name,
            points_selector=models.Filter(must=conditions),
            wait=True,
        )

    def invalidate_tenant(self, tenant_id: str) -> None:
        if self.client.collection_exists(self.collection_name):
            self.client.delete(
                collection_name=self.collection_name,
                points_selector=models.Filter(
                    must=[
                        models.FieldCondition(
                            key="tenant_id",
                            match=models.MatchValue(value=tenant_id),
                        )
                    ]
                ),
                wait=True,
            )
        self.invalidate_cache(tenant_id)
        self._current_corpus_versions.pop(tenant_id, None)

    def cache_entry_count(self, tenant_id: str, corpus_version: str) -> int:
        if not self.client.collection_exists(self.cache_collection_name):
            return 0
        return self.client.count(
            collection_name=self.cache_collection_name,
            count_filter=models.Filter(
                must=[
                    models.FieldCondition(
                        key="tenant_id", match=models.MatchValue(value=tenant_id)
                    ),
                    models.FieldCondition(
                        key="corpus_version",
                        match=models.MatchValue(value=corpus_version),
                    ),
                    models.FieldCondition(
                        key="expires_at",
                        range=models.Range(gt=time.time()),
                    ),
                ]
            ),
            exact=True,
        ).count

    def chunk_count(self, tenant_id: str, corpus_version: str | None) -> int:
        if not corpus_version or not self.client.collection_exists(self.collection_name):
            return 0
        return self.client.count(
            collection_name=self.collection_name,
            count_filter=models.Filter(
                must=[
                    models.FieldCondition(
                        key="tenant_id", match=models.MatchValue(value=tenant_id)
                    ),
                    models.FieldCondition(
                        key="corpus_version",
                        match=models.MatchValue(value=corpus_version),
                    ),
                ]
            ),
            exact=True,
        ).count

    def document_count(self, tenant_id: str, corpus_version: str | None) -> int:
        if not corpus_version or not self.client.collection_exists(self.collection_name):
            return 0
        document_ids: set[str] = set()
        offset = None
        while True:
            records, offset = self.client.scroll(
                collection_name=self.collection_name,
                scroll_filter=models.Filter(
                    must=[
                        models.FieldCondition(
                            key="tenant_id",
                            match=models.MatchValue(value=tenant_id),
                        ),
                        models.FieldCondition(
                            key="corpus_version",
                            match=models.MatchValue(value=corpus_version),
                        ),
                    ]
                ),
                offset=offset,
                limit=1000,
                with_payload=["document_id"],
                with_vectors=False,
            )
            for record in records:
                document_id = (record.payload or {}).get("document_id")
                if isinstance(document_id, str):
                    document_ids.add(document_id)
            if offset is None:
                break
        return len(document_ids)
