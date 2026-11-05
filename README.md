# Semantic Cache RAG

A local-development Retrieval-Augmented Generation (RAG) application with a FastAPI backend and a React + TypeScript frontend. It supports document upload and indexing, tenant-scoped retrieval and citations, a Qdrant-backed semantic answer cache, and optional answer-provider routing.

> **Project status:** This is a tested prototype suitable for learning, portfolio demonstrations, and local experimentation. It is **not production-ready**. Review the [security notes](#security-and-authentication) and [known limitations](#known-limitations) before exposing it to other users or networks.

## Features

- Upload UTF-8 text (`.txt`) and parseable PDF files.
- Split documents into overlapping chunks, create Sentence Transformers embeddings, and index them in Qdrant.
- Ask questions against the indexed corpus and return an answer status, citations, and retrieval scores.
- Cache answers semantically in Qdrant, scoped by tenant and corpus version, with a similarity threshold and TTL.
- Use local extractive answering by default, or configure an optional provider adapter and confidence-based escalation.
- Use the React workspace dashboard, document search/upload/delete/re-index tools, and a Markdown-enabled RAG chat with citations.
- Review backend-reported readiness, cache health, provider and embedding configuration, and bounded operational metrics; switch between light and dark themes.
- Run isolated automated tests using temporary corpus, Qdrant, and SQLite paths.

## Architecture

```text
React + TypeScript (Vite, cookie-based authentication)
          |
          | /api, /health, /ready
          v
FastAPI
  |-- Argon2 user authentication, short-lived JWT access, rotating refresh sessions
  |-- tenant-aware roles, document grants, CSRF protection, security audit events
  |-- document validation, parsing, chunking
  |-- Sentence Transformers embeddings
  |-- Qdrant document retrieval and semantic cache
  |-- local extractive or configured answer provider
  `-- bounded SQLite request metrics
```

In local development, the Vite server proxies API and health requests to `http://127.0.0.1:8000`. Browser authentication uses HttpOnly cookies; access and refresh tokens are not returned in JSON or stored in `localStorage`.

## Requirements

- Python 3.12 or newer.
- Node.js and npm versions compatible with the Vite version in `frontend/package.json`.
- Disk space and, on first use, network access to download the configured Sentence Transformers embedding model. The default model is `sentence-transformers/all-MiniLM-L6-v2`.
- No separate Qdrant server is needed for the default local configuration; embedded Qdrant data is stored under the configured local path.

## Run locally

Run these commands from the repository root in PowerShell.

### 1. Configure and install the backend

```powershell
Copy-Item .env.example .env
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
```

The example configuration enables built-in authentication with local Qdrant storage and the local extractive answer provider. Before starting the app, set a private signing key and apply the database migration:

```powershell
python -c "import secrets; print(secrets.token_urlsafe(48))"
# Copy the generated value into AUTH_SECRET_KEY in .env; never commit it.
# If DATABASE_URL differs from alembic.ini, set it in this shell before migrating:
# $env:DATABASE_URL = "sqlite:///./data/metrics.db"
alembic upgrade head
```

Keep `.env` private. `AUTHENTICATION_REQUIRED=true` requires an `AUTH_SECRET_KEY` of at least 32 characters. For production, configure HTTPS, secure origins, a remote HTTPS Qdrant service, and a managed secrets store; the local example must not be exposed to an untrusted network.

Start the backend bound to loopback:

```powershell
uvicorn backend.app.main:app --host 127.0.0.1 --port 8000
```

The first ingestion may take longer while the embedding model is downloaded and loaded.

### 2. Install and run the frontend

In a second terminal:

```powershell
cd frontend
npm ci
npm run dev
```

Open the local URL printed by Vite (normally `http://localhost:5173`). The development proxy forwards `/api`, `/auth`, `/health`, and `/ready` to the backend. Register to create a tenant and its first ADMIN account, then sign in.

### 3. Try the RAG workflow

1. Upload a small `.txt` or `.pdf` file from the Documents view.
2. The frontend requests ingestion after a successful upload.
3. Ask a question grounded in the uploaded document.
4. Review the answer status, provider, citations, retrieval scores, cache status, and metrics.
5. Ask a sufficiently similar question again to observe a possible cache hit. Similarity threshold and corpus contents affect whether a hit occurs.

The API is also available at `http://127.0.0.1:8000/docs` while running locally. Core routes are:

| Method | Route | Purpose |
|---|---|---|
| `GET` | `/health` | Liveness check |
| `GET` | `/ready` | Readiness/configuration check |
| `POST` | `/auth/register` | Register a new tenant and its first ADMIN account |
| `POST` | `/auth/login` | OAuth2 password-form login (`username`, `password`) |
| `POST` | `/auth/refresh` | Rotate the refresh token and issue a new access cookie |
| `POST` | `/auth/logout` | Revoke the current session |
| `GET` | `/auth/me` | Read the authenticated user's profile and role |
| `POST` | `/auth/change-password` | Change the current user's password and revoke sessions |
| `GET` / `POST` | `/auth/users` | ADMIN: list or add users within the tenant |
| `PATCH` | `/auth/users/{user_id}/role` | ADMIN: change a tenant user's role |
| `DELETE` | `/auth/users/{user_id}` | ADMIN: deactivate a tenant user |
| `GET` | `/api/v1/documents` | List documents the user is allowed to read |
| `POST` | `/api/v1/documents/upload` | ADMIN/EDITOR: upload a document as multipart field `file` |
| `DELETE` | `/api/v1/documents/{filename}` | ADMIN or an authorized EDITOR: delete a document |
| `GET` / `PUT` | `/api/v1/documents/{filename}/permissions` | ADMIN: read or replace document grants |
| `POST` | `/api/v1/ingest` | ADMIN/EDITOR: parse, chunk, embed, and index the tenant corpus |
| `POST` | `/api/v1/ask` | Query only permitted documents; e.g. `{"query":"What does it explain?","top_k":5}` |
| `GET` | `/api/v1/metrics` | Read tenant-scoped bounded metrics |
| `GET` | `/api/v1/settings` | ADMIN: read non-secret application settings |
| `GET` | `/api/v1/cache/stats` | Read tenant-scoped cache statistics |
| `POST` | `/api/v1/cache/invalidate` | Invalidate the current tenant's answer cache |

Unsafe browser requests require the CSRF cookie value in the `X-CSRF-Token` header. The frontend client handles this and refreshes the session when the access cookie expires. Tokens are never returned in API response bodies.

## Authentication and authorization

Every public signup creates a separate tenant; its first account is ADMIN. ADMINs invite additional users into their tenant. Email addresses are globally unique. Passwords are Argon2-hashed. JWT access cookies are short lived and validated against active server-side sessions; opaque refresh tokens are stored only as hashes, rotated on refresh, and revoked on logout, password changes, role changes, and account deactivation.

Authentication uses HttpOnly, SameSite=Strict cookies. The CSRF cookie is intentionally readable by the browser and must be echoed in `X-CSRF-Token` on unsafe requests. Cookies are Secure and use `__Host-` names in production; production must use HTTPS. The browser does not receive bearer tokens in JSON or store them in `localStorage`.

| Capability | ADMIN | EDITOR | VIEWER |
|---|---:|---:|---:|
| Manage tenant users and roles | Yes | No | No |
| Manage document permissions | Yes | No | No |
| Read all tenant documents | Yes | No | No |
| Read owned or explicitly granted documents | Yes | Yes | Yes |
| Upload new documents | Yes | Yes | No |
| Update/delete owned or edit-granted documents | Yes | Yes | No |
| Query RAG over permitted documents | Yes | Yes | Yes |
| Read tenant settings | Yes | No | No |

Document-level grants are managed using `PUT /api/v1/documents/{filename}/permissions`, with a `permissions` array of `{user_id, can_read, can_edit}` objects. Only active users in the same tenant can receive grants. Retrieval applies the permitted document IDs inside the vector-store query, and semantic-cache scope includes tenant, user, role, and the current allowed-document set.

The backend records security audit events for registration, successful and failed logins, logout, password changes, user administration, document upload/deletion, and permission changes. Audit records include actor/tenant/resource identifiers and timestamps, never passwords or token contents.

## Configuration

Copy `.env.example` for local use and inspect its comments for the available settings. Important options include:

| Setting | Purpose |
|---|---|
| `APP_ENV` | `development`, `testing`, or `production` |
| `CORPUS_DIR` | Root directory for local document corpora |
| `CHUNK_SIZE`, `CHUNK_OVERLAP` | Chunking parameters |
| `EMBEDDING_MODEL_NAME`, `EMBEDDING_DEVICE` | Embedding model and CPU/CUDA device |
| `QDRANT_USE_LOCAL_STORAGE`, `QDRANT_LOCAL_PATH` | Local embedded Qdrant configuration |
| `QDRANT_URL`, `QDRANT_API_KEY` | Remote Qdrant connection settings |
| `SEMANTIC_CACHE_ENABLED` | Enable or disable semantic cache use |
| `SEMANTIC_CACHE_THRESHOLD`, `SEMANTIC_CACHE_TTL_SECONDS` | Cache similarity threshold and lifetime |
| `LLM_PROVIDER` | `mock`, `ollama`, `groq`, `openai`, or `gemini` |
| `OPENAI_API_KEY`, `GROQ_API_KEY`, `GEMINI_API_KEY` | Optional provider credentials; supply outside source control |
| `OLLAMA_BASE_URL` | Ollama service URL |
| `PROVIDER_TIMEOUT_SECONDS`, `PROVIDER_RETRY_COUNT` | Provider request timeout and retry limit |
| `REQUIRE_TENANT_AUTH` | Legacy external signed-tenant-token mode |
| `AUTHENTICATION_REQUIRED` | Require built-in user authentication on protected API routes |
| `AUTH_SECRET_KEY`, `AUTH_ISSUER`, `AUTH_AUDIENCE` | JWT signing secret and token validation context |
| `AUTH_ACCESS_TOKEN_TTL_MINUTES`, `AUTH_REFRESH_TOKEN_TTL_DAYS` | Access lifetime and refresh-session lifetime |
| `AUTH_PASSWORD_MIN_LENGTH` | Minimum password length (12–128 characters) |
| `CORS_ALLOWED_ORIGINS` | Explicit browser origins allowed by CORS |
| `MAX_DOCUMENT_BYTES` | Maximum accepted document size |
| `RATE_LIMIT_REQUESTS_PER_MINUTE` | Per-process request limit per tenant |
| `DATABASE_URL`, `MAX_METRIC_RECORDS` | File-backed SQLite metrics database and record cap |

Settings are validated at application startup. Production mode rejects unsafe combinations including disabled built-in authentication, a weak/development signing key, debug mode, wildcard/localhost browser origins, and local or non-HTTPS remote Qdrant configuration. `REQUIRE_TENANT_AUTH` is the legacy tenant-token setting; built-in user auth is controlled by `AUTHENTICATION_REQUIRED`.

## Security and authentication

Built-in authentication is disabled by default in general development settings, but enabled in `.env.example`. Set `AUTHENTICATION_REQUIRED=true` and a strong `AUTH_SECRET_KEY` to require user authentication. When disabled, the legacy local-development tenant behavior remains; bind the server to loopback and do not treat it as a multi-user deployment. Legacy signed tenant tokens are accepted only while built-in authentication is disabled and do not provide user-level roles or permissions.

- When tenant auth is enabled, API clients send `Authorization: Bearer <signed-token>`. Tokens use HS256 and must contain a safe `tenant_id`, non-empty `sub`, matching `iss` and `aud`, numeric `iat` and `exp`, and a lifetime within `AUTH_MAX_TOKEN_TTL_SECONDS`.
- Tenant identity scopes document paths, vector retrieval, citations, cache entries/invalidation, and metrics. Tenant directory names are derived from tenant identifiers rather than using the raw identifier as a path.
- Uploads are restricted to `.txt` and `.pdf`, validated and size-limited, and stored under the tenant corpus directory. Upload and deletion invalidate that tenant's indexed corpus/cache.
- CORS must use explicit origins; wildcard origins are rejected. Cookie authentication uses SameSite restrictions, origin checks, and CSRF tokens on unsafe requests.
- `/health` and `/ready` are unauthenticated and do not return tenant content. Avoid exposing operational endpoints beyond what your deployment requires.
- External answer providers receive the user's question and retrieved document excerpts. Assess provider data handling, retention, and regional requirements before enabling them.

These controls are a starting point, not a substitute for deployment-specific threat modeling, penetration testing, and operational security.

## Answer providers and cost reporting

- `mock` is the default and uses local extractive answering; it does not make an external model request.
- `openai`, `groq`, and `gemini` use their configured provider adapters and require credentials supplied through environment variables or a secret manager.
- `ollama` sends requests to `OLLAMA_BASE_URL`; the Ollama service and selected model must already be available.
- The routing layer can escalate from the configured cheaper route to the stronger route when the returned confidence is below the configured threshold, subject to the retry limit.
- Cost is calculated from configured per-million-token prices and provider-reported usage. Providers that omit usage can result in zero reported cost. A request that times out after the provider has processed it may still incur a charge that this application cannot observe.
- Confidence is not independently calibrated or guaranteed to represent factual correctness. Validate provider, model, pricing, and escalation behavior for your own configuration.

Automated tests mock provider responses. They do not verify live provider credentials, model availability, provider billing, or current third-party API behavior.

## Semantic cache behavior

Cache entries are stored in Qdrant with tenant and corpus-version metadata, answer/citation/provider details, and an expiry timestamp. A lookup must meet the configured similarity threshold and must not be expired. Upload, deletion, re-ingestion, corpus-version change, and explicit invalidation clear relevant tenant cache/index state. Recognized cache storage/network failures are logged without query or document contents and the request falls back to retrieval and answer generation.

The cache is an optimization, not a correctness guarantee. Similarity matches can be inappropriate for some workloads; tune the threshold and TTL, and evaluate answer quality and cache behavior against representative data before use.

## Data, persistence, and operations

- Uploaded documents are stored as files under `CORPUS_DIR`; local Qdrant stores vectors/cache data under `QDRANT_LOCAL_PATH`; SQLite stores bounded request summaries under `DATABASE_URL`.
- Tenant-isolated corpus folders are used when tenant isolation is enabled. Do not place private or production documents in the repository's sample/local data directories.
- Metrics retain request summaries and aggregate usage, not full user queries or document contents. They are bounded by `MAX_METRIC_RECORDS`.
- Auth persistence and bounded request metrics use the configured file-backed SQLite `DATABASE_URL`; authentication schema changes are managed with Alembic. The current implementation does not provide PostgreSQL support or distributed analytics.
- The rate limiter is process-local and its state is not shared among workers or instances.
- Embedded/local Qdrant is for single-process development. Do not share its storage directory among multiple server processes. Production configuration expects HTTPS remote Qdrant with an API key.
- Back up and protect document files, vector-store data, metrics databases, and signing keys according to your own retention and recovery requirements.
- There are no Dockerfile or Docker Compose deployment definitions in this repository.

## Tests and quality checks

Install the development dependencies with `python -m pip install -e ".[dev]"`, run `alembic upgrade head` after setting `DATABASE_URL`, then run from the repository root:

```powershell
python -m pytest
ruff check backend tests
ruff format --check backend/app/api backend/app/core/config.py backend/app/core/database.py backend/app/main.py backend/app/models/auth.py backend/app/repositories/qdrant_vector_store.py backend/app/schemas/api.py backend/app/schemas/auth.py backend/app/services/auth_service.py backend/app/services/document_permissions.py backend/app/services/rag_service.py backend/migrations tests/integration/test_auth_rbac.py tests/unit/test_environment.py
python -m compileall -q backend tests
```

Run frontend checks from `frontend`:

```powershell
npm ci
npm test
npm run lint
npm run build
```

The integration tests configure temporary corpus directories, temporary Qdrant storage, and a temporary SQLite database. They do not need to read `.env`, use the existing corpus/Qdrant data, or make live provider calls. Do not point tests or local experiments at data you need to preserve.

For an environment-only check that does not load `.env`:

```powershell
python scripts/verify_env.py
```

## Known limitations

- **Not production-ready or security-certified.** The project has not undergone an independent security audit or deployment-specific load, resilience, or penetration testing.
- **Built-in identity scope:** local password authentication and tenant RBAC are implemented, but there is no SSO/OIDC/JWKS integration, MFA, email verification, password reset, signing-key rotation, or organization identity lifecycle.
- **Signup behavior:** public signup creates a new tenant and an ADMIN account. A tenant admin must provision additional users; signup does not join an existing tenant.
- **Existing content migration:** the authentication migration adds tables but does not assign existing corpus files or vector records to a tenant/user. Back up and deliberately migrate or re-upload existing content before enabling authenticated access to it.
- **Audit operations:** audit events are stored in the application database but are not exported to a centralized append-only security information and event management (SIEM) system.
- **Single-process operational features:** rate limiting is process-local; local embedded Qdrant is single-process only.
- **Storage constraints:** auth and metrics storage currently support SQLite only; there is no PostgreSQL backend.
- **Provider verification:** automated tests mock provider responses; live OpenAI, Groq, Gemini, and Ollama calls are not part of the test suite. Reported cost may differ from actual billed cost.
- **Model quality:** local extractive answers and provider confidence are not guarantees of factual correctness; retrieval can miss relevant passages or return weak matches.
- **Document safety:** no antivirus scanning, malware detection, PDF sandbox, OCR for scanned PDFs, or formal document-retention workflow is included.
- **Deployment tooling:** no Docker/Compose files, shared rate limiter, centralized logging/monitoring, automated backups, or disaster-recovery setup is provided.
- **Legacy vector data:** vectors created before tenant/corpus scoping may not be recognized by the current scoped retrieval flow. Back up existing data and re-index through the current application as appropriate; no automatic legacy migration is provided.
