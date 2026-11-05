import time
from collections.abc import Sequence
from pathlib import Path

import jwt
from fastapi.testclient import TestClient
from sqlalchemy import select

from backend.app.core.config import Settings
from backend.app.main import create_app
from backend.app.models.auth import AuditEvent, AuthSession
from backend.app.repositories.qdrant_vector_store import QdrantVectorStore
from backend.app.services.answer_provider import ExtractiveAnswerProvider
from backend.app.services.chunking import TextChunker
from backend.app.services.document_loader import DocumentLoader
from backend.app.services.rag_service import RagService

SECRET = "tests-only-auth-signing-secret-with-adequate-length"


class WordTokenizer:
    def __init__(self) -> None:
        self.word_to_id: dict[str, int] = {}
        self.id_to_word: dict[int, str] = {}

    def encode(
        self,
        text: str,
        *,
        add_special_tokens: bool = False,
        truncation: bool = False,
    ) -> list[int]:
        del add_special_tokens, truncation
        token_ids = []
        for word in text.split():
            if word not in self.word_to_id:
                token_id = len(self.word_to_id)
                self.word_to_id[word] = token_id
                self.id_to_word[token_id] = word
            token_ids.append(self.word_to_id[word])
        return token_ids

    def decode(
        self,
        token_ids: Sequence[int],
        *,
        skip_special_tokens: bool = True,
        clean_up_tokenization_spaces: bool = True,
    ) -> str:
        del skip_special_tokens, clean_up_tokenization_spaces
        return " ".join(self.id_to_word[token_id] for token_id in token_ids)


class FakeEmbedder:
    def __init__(self) -> None:
        self.tokenizer = WordTokenizer()
        self.dimension = 2

    def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        return [[1.0, 0.0] for _ in texts]

    def embed_query(self, text: str) -> list[float]:
        del text
        return [1.0, 0.0]


def _client(tmp_path: Path, *, with_rag: bool = False) -> tuple[TestClient, object]:
    settings = Settings(
        _env_file=None,
        APP_ENV="testing",
        AUTHENTICATION_REQUIRED=True,
        AUTH_SECRET_KEY=SECRET,
        AUTH_ACCESS_TOKEN_TTL_MINUTES=15,
        AUTH_REFRESH_TOKEN_TTL_DAYS=2,
        CORPUS_DIR=str(tmp_path / "documents"),
        qdrant_path=tmp_path / "qdrant",
        DATABASE_URL=f"sqlite:///{tmp_path / 'auth.sqlite3'}",
        SEMANTIC_CACHE_THRESHOLD=0.9,
        chunk_size_tokens=64,
        chunk_overlap_tokens=4,
    )
    service = object()
    if with_rag:
        embedder = FakeEmbedder()
        service = RagService(
            loader=DocumentLoader(settings.documents_dir, settings.max_document_bytes),
            chunker=TextChunker(embedder.tokenizer, 64, 4),
            embedder=embedder,
            vector_store=QdrantVectorStore(
                path=str(settings.qdrant_path),
                collection_name="auth_rag_documents",
                vector_size=2,
                cache_collection_name="auth_rag_cache",
            ),
            answer_provider=ExtractiveAnswerProvider(),
            min_retrieval_score=0.2,
            semantic_cache_enabled=True,
            cache_threshold=settings.SEMANTIC_CACHE_THRESHOLD,
            cache_ttl_seconds=120,
            tenant_isolation_enabled=True,
        )
    app = create_app(settings=settings, service=service)
    return TestClient(app), app


def _register(client: TestClient, email: str = "admin@example.com") -> dict[str, str]:
    response = client.post(
        "/auth/register",
        json={
            "email": email,
            "display_name": "Tenant Admin",
            "tenant_name": "Private Workspace",
            "password": "a-very-long-password-for-tests",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def _csrf(client: TestClient) -> dict[str, str]:
    csrf_cookies = [cookie.value for cookie in client.cookies.jar if cookie.name == "csrf_token"]
    return {"X-CSRF-Token": csrf_cookies[-1] if csrf_cookies else ""}


def _cookie_snapshot(client: TestClient) -> dict[str, str]:
    return {cookie.name: cookie.value for cookie in client.cookies.jar}


def _use_cookies(client: TestClient, values: dict[str, str]) -> None:
    client.cookies.clear()
    for name, value in values.items():
        client.cookies.set(name, value, domain="testserver.local", path="/")


def test_registration_duplicate_password_hash_and_auth_audit(tmp_path: Path) -> None:
    client, app = _client(tmp_path)
    with client:
        assert client.get("/api/v1/documents").status_code == 401
        user = _register(client)
        assert user["role"] == "ADMIN"
        assert user["tenant_id"]
        assert "password_hash" not in user
        assert "access_token" not in user
        duplicate = client.post(
            "/auth/register",
            json={
                "email": "ADMIN@example.com",
                "display_name": "Duplicate",
                "tenant_name": "Another workspace",
                "password": "a-very-long-password-for-tests",
            },
        )
        assert duplicate.status_code == 409
        assert client.get("/api/v1/documents").status_code == 200
        with app.state.db_session_factory() as db:
            stored_session = db.scalar(select(AuthSession))
            audit_actions = set(db.scalars(select(AuditEvent.action)).all())
        assert stored_session is not None
        assert stored_session.refresh_token_hash != client.cookies.get("refresh_token")
        assert "user.registered" in audit_actions


def test_login_invalid_password_expired_and_invalid_jwt(tmp_path: Path) -> None:
    client, _app = _client(tmp_path)
    with client:
        _register(client)
        client.post("/auth/logout", headers=_csrf(client))
        invalid = client.post(
            "/auth/login",
            data={"username": "admin@example.com", "password": "incorrect-password"},
        )
        assert invalid.status_code == 401
        assert invalid.json()["detail"] == "Invalid email or password."

        valid = client.post(
            "/auth/login",
            data={"username": "admin@example.com", "password": "a-very-long-password-for-tests"},
        )
        assert valid.status_code == 200
        assert "httponly" in valid.headers["set-cookie"].lower()
        assert "samesite=strict" in valid.headers["set-cookie"].lower()

        now = int(time.time())
        expired = jwt.encode(
            {
                "sub": "missing-user",
                "tid": "missing-tenant",
                "sid": "missing-session",
                "jti": "expired-token",
                "token_type": "access",
                "iss": "semantic-cache-rag",
                "aud": "semantic-cache-rag-api",
                "iat": now - 120,
                "exp": now - 60,
            },
            SECRET,
            algorithm="HS256",
        )
        invalid_signature = jwt.encode(
            {
                "sub": "missing-user",
                "tid": "missing-tenant",
                "sid": "missing-session",
                "jti": "invalid-signature",
                "token_type": "access",
                "iss": "semantic-cache-rag",
                "aud": "semantic-cache-rag-api",
                "iat": now,
                "exp": now + 60,
            },
            "different-signing-secret-with-32-chars",
            algorithm="HS256",
        )
        assert (
            client.get("/auth/me", headers={"Authorization": f"Bearer {expired}"}).status_code
            == 401
        )
        assert (
            client.get(
                "/auth/me", headers={"Authorization": f"Bearer {invalid_signature}"}
            ).status_code
            == 401
        )


def test_refresh_rotation_logout_revocation_and_password_change(tmp_path: Path) -> None:
    client, _app = _client(tmp_path)
    with client:
        _register(client)
        old_access = client.cookies.get("access_token")
        old_refresh = client.cookies.get("refresh_token")
        rotated = client.post("/auth/refresh", headers=_csrf(client))
        assert rotated.status_code == 200
        new_access = client.cookies.get("access_token")
        assert new_access != old_access
        assert client.cookies.get("refresh_token") != old_refresh
        assert (
            client.get("/auth/me", headers={"Authorization": f"Bearer {old_access}"}).status_code
            == 401
        )

        csrf_token = client.cookies.get("csrf_token")
        client.cookies.set("refresh_token", old_refresh, domain="testserver.local", path="/")
        replay = client.post("/auth/refresh", headers=_csrf(client))
        assert replay.status_code == 401
        _use_cookies(client, {"access_token": new_access, "csrf_token": csrf_token})
        logout = client.post("/auth/logout", headers=_csrf(client))
        assert logout.status_code == 204
        assert (
            client.get("/auth/me", headers={"Authorization": f"Bearer {new_access}"}).status_code
            == 401
        )

        login = client.post(
            "/auth/login",
            data={"username": "admin@example.com", "password": "a-very-long-password-for-tests"},
        )
        assert login.status_code == 200
        password_change = client.post(
            "/auth/change-password",
            headers=_csrf(client),
            json={
                "current_password": "a-very-long-password-for-tests",
                "new_password": "a-different-long-password-for-tests",
            },
        )
        assert password_change.status_code == 204
        client.post("/auth/logout", headers=_csrf(client))
        assert (
            client.post(
                "/auth/login",
                data={
                    "username": "admin@example.com",
                    "password": "a-very-long-password-for-tests",
                },
            ).status_code
            == 401
        )
        assert (
            client.post(
                "/auth/login",
                data={
                    "username": "admin@example.com",
                    "password": "a-different-long-password-for-tests",
                },
            ).status_code
            == 200
        )


def test_rbac_tenant_and_document_permission_cache_isolation(tmp_path: Path) -> None:
    client, _app = _client(tmp_path, with_rag=True)
    with client:
        admin = _register(client)
        admin_cookies = _cookie_snapshot(client)
        for name, content in (
            ("alpha.txt", "The alpha record describes a private green orchard."),
            ("bravo.txt", "The bravo record describes a private blue harbor."),
        ):
            upload = client.post(
                "/api/v1/documents/upload",
                headers=_csrf(client),
                files={"file": (name, content.encode(), "text/plain")},
            )
            assert upload.status_code == 200, upload.text
        assert client.post("/api/v1/ingest", headers=_csrf(client)).status_code == 200

        editor_response = client.post(
            "/auth/users",
            headers=_csrf(client),
            json={
                "email": "editor@example.com",
                "display_name": "Editor",
                "password": "editor-account-long-password",
                "role": "EDITOR",
            },
        )
        viewer_response = client.post(
            "/auth/users",
            headers=_csrf(client),
            json={
                "email": "viewer@example.com",
                "display_name": "Viewer",
                "password": "viewer-account-long-password",
                "role": "VIEWER",
            },
        )
        assert editor_response.status_code == 201, editor_response.text
        assert viewer_response.status_code == 201, viewer_response.text
        editor_id = editor_response.json()["id"]
        viewer_id = viewer_response.json()["id"]
        editor_login = client.post(
            "/auth/login",
            data={"username": "editor@example.com", "password": "editor-account-long-password"},
        )
        assert editor_login.status_code == 200
        editor_cookies = _cookie_snapshot(client)
        assert client.get("/auth/users").status_code == 403
        assert client.get("/api/v1/settings").status_code == 403
        assert client.get("/api/v1/documents").json()["total_count"] == 0
        assert (
            client.post(
                "/api/v1/documents/upload",
                headers=_csrf(client),
                files={"file": ("blocked.txt", b"viewer and editor authorization", "text/plain")},
            ).status_code
            == 200
        )
        assert client.post("/api/v1/ingest", headers=_csrf(client)).status_code == 200
        assert (
            client.delete("/api/v1/documents/alpha.txt", headers=_csrf(client)).status_code == 403
        )
        before_access_response = client.post(
            "/api/v1/ask", headers=_csrf(client), json={"query": "Describe the orchard"}
        )
        assert before_access_response.status_code == 200, before_access_response.text
        before_access = before_access_response.json()
        assert before_access["status"] == "insufficient_evidence"

        _use_cookies(client, admin_cookies)
        grant_alpha = client.put(
            "/api/v1/documents/alpha.txt/permissions",
            headers=_csrf(client),
            json={"permissions": [{"user_id": editor_id, "can_read": True}]},
        )
        assert grant_alpha.status_code == 200, grant_alpha.text
        _use_cookies(client, editor_cookies)
        alpha_response = client.post(
            "/api/v1/ask",
            headers=_csrf(client),
            json={"query": "Describe the private record"},
        )
        assert alpha_response.status_code == 200, alpha_response.text
        alpha_answer = alpha_response.json()
        assert alpha_answer["status"] == "supported"
        assert {citation["source_path"] for citation in alpha_answer["citations"]} == {"alpha.txt"}

        _use_cookies(client, admin_cookies)
        grant_bravo = client.put(
            "/api/v1/documents/alpha.txt/permissions",
            headers=_csrf(client),
            json={"permissions": []},
        )
        assert grant_bravo.status_code == 200
        grant_bravo = client.put(
            "/api/v1/documents/bravo.txt/permissions",
            headers=_csrf(client),
            json={"permissions": [{"user_id": editor_id, "can_read": True}]},
        )
        assert grant_bravo.status_code == 200
        _use_cookies(client, editor_cookies)
        bravo_response = client.post(
            "/api/v1/ask",
            headers=_csrf(client),
            json={"query": "Describe the private record"},
        )
        assert bravo_response.status_code == 200, bravo_response.text
        bravo_answer = bravo_response.json()
        assert bravo_answer["status"] == "supported"
        assert {citation["source_path"] for citation in bravo_answer["citations"]} == {"bravo.txt"}
        assert bravo_answer["cache_hit"] is False

        _use_cookies(client, admin_cookies)
        edit_grant = client.put(
            "/api/v1/documents/alpha.txt/permissions",
            headers=_csrf(client),
            json={"permissions": [{"user_id": editor_id, "can_read": True, "can_edit": True}]},
        )
        assert edit_grant.status_code == 200
        _use_cookies(client, editor_cookies)
        edit_upload = client.post(
            "/api/v1/documents/upload",
            headers=_csrf(client),
            files={
                "file": (
                    "alpha.txt",
                    b"The alpha record describes a private green orchard.",
                    "text/plain",
                )
            },
        )
        assert edit_upload.status_code == 200, edit_upload.text
        assert client.post("/api/v1/ingest", headers=_csrf(client)).status_code == 200

        _use_cookies(client, admin_cookies)
        grant_viewer = client.put(
            "/api/v1/documents/alpha.txt/permissions",
            headers=_csrf(client),
            json={"permissions": [{"user_id": viewer_id, "can_read": True}]},
        )
        assert grant_viewer.status_code == 200
        viewer_login = client.post(
            "/auth/login",
            data={"username": "viewer@example.com", "password": "viewer-account-long-password"},
        )
        assert viewer_login.status_code == 200
        assert client.get("/api/v1/documents").json()["total_count"] == 1
        assert client.get("/api/v1/settings").status_code == 403
        viewer_answer_response = client.post(
            "/api/v1/ask",
            headers=_csrf(client),
            json={"query": "Describe the private record"},
        )
        assert viewer_answer_response.status_code == 200, viewer_answer_response.text
        assert {
            citation["source_path"] for citation in viewer_answer_response.json()["citations"]
        } == {"alpha.txt"}
        assert (
            client.delete("/api/v1/documents/alpha.txt", headers=_csrf(client)).status_code == 403
        )
        assert (
            client.post(
                "/api/v1/documents/upload",
                headers=_csrf(client),
                files={"file": ("viewer.txt", b"no upload", "text/plain")},
            ).status_code
            == 403
        )

        tenant_b = client.post(
            "/auth/register",
            json={
                "email": "other-tenant@example.com",
                "display_name": "Other Admin",
                "tenant_name": "Other Tenant",
                "password": "other-tenant-long-password",
            },
        )
        assert tenant_b.status_code == 201
        assert tenant_b.json()["tenant_id"] != admin["tenant_id"]
        assert client.get("/api/v1/documents").json()["total_count"] == 0
        tenant_b_answer_response = client.post(
            "/api/v1/ask",
            headers=_csrf(client),
            json={"query": "Describe the private record"},
        )
        assert tenant_b_answer_response.status_code == 200, tenant_b_answer_response.text
        tenant_b_answer = tenant_b_answer_response.json()
        assert tenant_b_answer["status"] == "insufficient_evidence"
        assert tenant_b_answer["citations"] == []
