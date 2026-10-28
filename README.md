# Semantic Cache RAG

A local-development Retrieval-Augmented Generation (RAG) application with a FastAPI backend and a React + TypeScript frontend. It supports document upload and indexing, tenant-scoped retrieval and citations, a Qdrant-backed semantic answer cache, and optional answer-provider routing.

> **Project status:** This is a tested prototype suitable for learning, portfolio demonstrations, and local experimentation. It is **not production-ready**. Review the [security notes](#security-and-authentication) and [known limitations](#known-limitations) before exposing it to other users or networks.

## Features

- Upload UTF-8 text (`.txt`) and parseable PDF files.
- Split documents into overlapping chunks, create Sentence Transformers embeddings, and index them in Qdrant.
- Ask questions against the indexed corpus and return an answer status, citations, and retrieval scores.
- Cache answers semantically in Qdrant, scoped by tenant and corpus version, with a similarity threshold and TTL.
- Use local extractive answering by default, or configure an optional provider adapter and confidence-based escalation.
- View documents, cache statistics, settings, and bounded operational metrics in the React interface.
- Run isolated automated tests using temporary corpus, Qdrant, and SQLite paths.

## Architecture

```text
React + TypeScript (Vite)
          |
          | /api, /health, /ready
          v
FastAPI
  |-- document validation, parsing, chunking
  |-- Sentence Transformers embeddings
  |-- Qdrant document retrieval and semantic cache
  |-- local extractive or configured answer provider
  `-- bounded SQLite request metrics
```

In local development, the Vite server proxies API and health requests to `http://127.0.0.1:8000`. The frontend does not contain secrets and does not provide a login or bearer-token management screen.

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

The example configuration uses development mode, local Qdrant storage, the local extractive answer provider, and a single default tenant without API authentication. This is convenient for a local demo only; **do not expose this configuration to an untrusted network**. Keep `.env` private and do not commit it.

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

Open the local URL printed by Vite (normally `http://localhost:5173`). The development proxy forwards `/api`, `/health`, and `/ready` to the backend. The UI is intended for the unauthenticated local-development configuration. It cannot call a backend that requires bearer-token authentication.

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
| `GET` | `/api/v1/documents` | List the current tenant's documents |
| `POST` | `/api/v1/documents/upload` | Upload a document as multipart field `file` |
| `DELETE` | `/api/v1/documents/{filename}` | Delete a tenant document and invalidate its index/cache |
| `POST` | `/api/v1/ingest` | Parse, chunk, embed, and index the tenant corpus |
| `POST` | `/api/v1/ask` | Ask a question, e.g. `{"query":"What does the document explain?","top_k":5}` |
| `GET` | `/api/v1/metrics` | Read tenant-scoped bounded metrics |
| `GET` | `/api/v1/settings` | Read non-secret application settings |
| `GET` | `/api/v1/cache/stats` | Read tenant-scoped cache statistics |
| `POST` | `/api/v1/cache/invalidate` | Invalidate the current tenant's answer cache |

All `/api/v1/*` routes use the development tenant when auth is disabled, or the validated tenant identity when auth is enabled.

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
| `REQUIRE_TENANT_AUTH`, `AUTH_SECRET_KEY` | Enable and configure signed tenant tokens |
| `CORS_ALLOWED_ORIGINS` | Explicit browser origins allowed by CORS |
| `MAX_DOCUMENT_BYTES` | Maximum accepted document size |
| `RATE_LIMIT_REQUESTS_PER_MINUTE` | Per-process request limit per tenant |
| `DATABASE_URL`, `MAX_METRIC_RECORDS` | File-backed SQLite metrics database and record cap |

Settings are validated at application startup. Production mode rejects unsafe combinations including disabled tenant auth, a weak/development signing key, debug mode, wildcard/localhost browser origins, and local or non-HTTPS remote Qdrant configuration.

## Security and authentication

- In development, API authentication is disabled by default and requests share the configured `DEFAULT_TENANT_ID`. The development server should remain bound to loopback and must not be treated as a multi-user deployment.
- When tenant auth is enabled, API clients send `Authorization: Bearer <signed-token>`. Tokens use HS256 and must contain a safe `tenant_id`, non-empty `sub`, matching `iss` and `aud`, numeric `iat` and `exp`, and a lifetime within `AUTH_MAX_TOKEN_TTL_SECONDS`.
- The backend validates tokens but does **not** provide a user database, login endpoint, token issuance, refresh flow, account management, or role/permission system. A trusted identity provider must issue tokens that follow the configured contract. Never put the signing key in the frontend.
- Tenant identity scopes document paths, vector retrieval, citations, cache entries/invalidation, and metrics. Tenant directory names are derived from tenant identifiers rather than using the raw identifier as a path.
- Uploads are restricted to `.txt` and `.pdf`, validated and size-limited, and stored under the tenant corpus directory. Upload and deletion invalidate that tenant's indexed corpus/cache.
- CORS must use explicit origins; wildcard origins are rejected. Authentication uses bearer headers, not cookies.
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
- The metrics implementation supports file-backed SQLite only. It does not provide PostgreSQL support, distributed analytics, or a migration framework.
- The rate limiter is process-local and its state is not shared among workers or instances.
- Embedded/local Qdrant is for single-process development. Do not share its storage directory among multiple server processes. Production configuration expects HTTPS remote Qdrant with an API key.
- Back up and protect document files, vector-store data, metrics databases, and signing keys according to your own retention and recovery requirements.
- There are no Dockerfile or Docker Compose deployment definitions in this repository.

## Tests and quality checks

Install the development dependencies with `python -m pip install -e ".[dev]"`, then run from the repository root:

```powershell
python -m pytest
ruff check .
ruff format --check backend tests scripts
python -m compileall -q backend tests
```

Run frontend checks from `frontend`:

```powershell
npm ci
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
- **No built-in identity lifecycle:** no login, users/passwords, token issuance/refresh, JWKS, key rotation, revocation, or fine-grained roles. External identity-provider integration is required.
- **Single-process operational features:** rate limiting is process-local; local embedded Qdrant is single-process only.
- **Storage constraints:** metrics support SQLite only; there is no PostgreSQL backend or database migration system.
- **Provider verification:** automated tests mock provider responses; live OpenAI, Groq, Gemini, and Ollama calls are not part of the test suite. Reported cost may differ from actual billed cost.
- **Model quality:** local extractive answers and provider confidence are not guarantees of factual correctness; retrieval can miss relevant passages or return weak matches.
- **Document safety:** no antivirus scanning, malware detection, PDF sandbox, OCR for scanned PDFs, or formal document-retention workflow is included.
- **Deployment tooling:** no Docker/Compose files, production frontend auth flow, shared rate limiter, centralized logging/monitoring, automated backups, or disaster-recovery setup is provided.
- **Legacy vector data:** vectors created before tenant/corpus scoping may not be recognized by the current scoped retrieval flow. Back up existing data and re-index through the current application as appropriate; no automatic legacy migration is provided.


