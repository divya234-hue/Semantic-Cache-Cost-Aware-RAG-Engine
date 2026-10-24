# RAG Studio frontend

This React + TypeScript app is a local-development interface for the FastAPI backend. It uses the backend's existing document, ingestion, ask, metrics, settings, cache-statistics, and readiness endpoints.

## Run locally

1. Start the FastAPI backend from the repository root on `http://127.0.0.1:8000`.
2. In a second terminal:

   ```powershell
   cd frontend
   npm ci
   npm run dev
   ```

3. Open the Vite URL shown in the terminal (normally `http://localhost:5173`).

The Vite development server proxies `/api`, `/health`, and `/ready` to the local backend. No API host, token, or secret is hardcoded into the client. The UI does not manage bearer tokens; use it only with the backend's unauthenticated development mode. When tenant auth is required, use an API client that can attach a valid bearer token.

## Build and lint

```powershell
npm run build
npm run lint
```

The build runs the TypeScript project checks before creating the Vite production bundle.

## Backend behavior shown in the UI

- Document upload writes into the current tenant's corpus folder. Uploading a name that already exists asks for confirmation because the backend replaces that file. Upload/delete invalidates that tenant's index and cache; after upload, the UI ingests and refreshes documents and metrics.
- Questions request five passages and display the answer status, the provider returned by the API, citations, and raw retrieval scores.
- Cache-hit state, selected route, escalation, and reported cost are shown with each answer. In the default local-development mode, requests use the default development tenant. Metrics are retained in a bounded SQLite history; query text and document contents are not stored.
- Semantic cache lookup uses tenant, corpus version, similarity threshold, and TTL. Qdrant cache failures are logged without content and the RAG request can continue uncached.
- The default provider is local extractive code. External provider adapters are opt-in and receive the question plus retrieved excerpts; only provider-reported token usage is used to calculate costs.
- Do not upload private documents to an exposed development server. Production mode requires signed tenant bearer tokens, but this UI does not provide a token-entry or login flow.
