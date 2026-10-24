import axios from 'axios'

export interface DocumentInfo {
  name: string
  path: string
  size_bytes: number
  extension: string
  modified_at: string
}

export interface DocumentListResponse {
  documents: DocumentInfo[]
  total_count: number
  corpus_dir: string
}

export interface DocumentUploadResponse {
  filename: string
  size_bytes: number
  message: string
}

export interface IngestResponse {
  documents_ingested: number
  chunks_indexed: number
  corpus_version: string
}

export interface Citation {
  document_id: string
  chunk_id: string
  source_path: string
  retrieval_score: number
}

export interface AskResponse {
  status: 'supported' | 'insufficient_evidence'
  answer: string
  citations: Citation[]
  provider: string
  model?: string | null
  cache_hit: boolean
  route: 'cheap' | 'strong'
  escalated: boolean
  cost_usd: number
  input_tokens: number
  output_tokens: number
}

export interface MetricsSummary {
  total_requests: number
  cache_hit_count: number
  cache_miss_count: number
  cache_hit_rate: number
  avg_latency_ms: number
  p50_latency_ms: number
  p95_latency_ms: number
  total_cost_usd: number
  cheap_route_count: number
  strong_route_count: number
  escalated_count: number
  total_input_tokens: number
  total_output_tokens: number
  indexed_documents: number
  indexed_chunks: number
}

export interface SystemSettings {
  app_name: string
  app_env: string
  log_level: string
  corpus_dir: string
  corpus_version: string
  embedding_model: string
  embedding_dimension: number
  qdrant_local_path: string
  qdrant_collection: string
  semantic_cache_enabled: boolean
  cache_threshold: number
  cache_ttl_seconds: number
  llm_provider: string
  cheap_model: string
  strong_model: string
  escalation_enabled: boolean
  cheap_input_price: number
  cheap_output_price: number
  strong_input_price: number
  strong_output_price: number
  tenant_auth_enabled: boolean
}

export interface CacheStats {
  enabled: boolean
  threshold: number
  ttl_seconds: number
  total_entries: number
  hits: number
  misses: number
  corpus_version: string
}

export interface HealthResponse {
  status: 'ok' | 'ready'
}

const client = axios.create({
  timeout: 30_000,
})

export const ragApi = {
  async getReadiness(): Promise<HealthResponse> {
    return (await client.get<HealthResponse>('/ready')).data
  },
  async listDocuments(): Promise<DocumentListResponse> {
    return (await client.get<DocumentListResponse>('/api/v1/documents')).data
  },
  async uploadDocument(file: File): Promise<DocumentUploadResponse> {
    const body = new FormData()
    body.append('file', file)
    return (await client.post<DocumentUploadResponse>('/api/v1/documents/upload', body)).data
  },
  async ingestDocuments(): Promise<IngestResponse> {
    return (await client.post<IngestResponse>('/api/v1/ingest')).data
  },
  async ask(query: string): Promise<AskResponse> {
    return (
      await client.post<AskResponse>('/api/v1/ask', {
        query,
        top_k: 5,
      })
    ).data
  },
  async getMetrics(): Promise<MetricsSummary> {
    return (await client.get<MetricsSummary>('/api/v1/metrics')).data
  },
  async getSettings(): Promise<SystemSettings> {
    return (await client.get<SystemSettings>('/api/v1/settings')).data
  },
  async getCacheStats(): Promise<CacheStats> {
    return (await client.get<CacheStats>('/api/v1/cache/stats')).data
  },
}

export function getApiErrorMessage(error: unknown): string {
  if (axios.isAxiosError<{ detail?: unknown }>(error)) {
    const detail = error.response?.data?.detail
    if (typeof detail === 'string' && detail.trim()) return detail
    if (error.response?.status) {
      return `The API returned an error (${error.response.status}). Please try again.`
    }
    return 'Could not reach the local API. Check that the backend is running on port 8000.'
  }

  return error instanceof Error ? error.message : 'An unexpected error occurred.'
}
