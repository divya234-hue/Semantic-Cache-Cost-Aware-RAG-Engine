import {
  Activity,
  ArrowUpRight,
  BookOpen,
  Database,
  FileText,
  Gauge,
  LayoutDashboard,
  MessageSquareText,
  RefreshCw,
  Search,
  Settings2,
  ShieldAlert,
  Sparkles,
  Zap,
} from 'lucide-react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import type { FormEvent } from 'react'
import { AnswerCard } from './components/AnswerCard'
import { DocumentList } from './components/DocumentList'
import { MetricCard } from './components/MetricCard'
import {
  getApiErrorMessage,
  ragApi,
} from './api'
import type {
  AskResponse,
  CacheStats,
  DocumentListResponse,
  IngestResponse,
  MetricsSummary,
  SystemSettings,
} from './api'
import './App.css'

type Page = 'documents' | 'ask' | 'system'

function formatNumber(value: number): string {
  return new Intl.NumberFormat().format(value)
}

function formatCurrency(value: number): string {
  return new Intl.NumberFormat(undefined, {
    style: 'currency',
    currency: 'USD',
    maximumFractionDigits: 4,
  }).format(value)
}

function SettingRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="setting-row">
      <span>{label}</span>
      <strong title={value}>{value}</strong>
    </div>
  )
}

function App() {
  const queryClient = useQueryClient()
  const [page, setPage] = useState<Page>('documents')
  const [uploading, setUploading] = useState(false)
  const [uploadMessage, setUploadMessage] = useState<string | null>(null)
  const [uploadError, setUploadError] = useState<string | null>(null)
  const [query, setQuery] = useState('')
  const [answer, setAnswer] = useState<AskResponse | null>(null)
  const [asking, setAsking] = useState(false)
  const [askError, setAskError] = useState<string | null>(null)

  const documentsQuery = useQuery({
    queryKey: ['documents'],
    queryFn: ragApi.listDocuments,
    retry: false,
    refetchOnWindowFocus: false,
  })
  const metricsQuery = useQuery({
    queryKey: ['metrics'],
    queryFn: ragApi.getMetrics,
    retry: false,
    refetchOnWindowFocus: false,
  })
  const settingsQuery = useQuery({
    queryKey: ['settings'],
    queryFn: ragApi.getSettings,
    retry: false,
    refetchOnWindowFocus: false,
  })
  const cacheQuery = useQuery({
    queryKey: ['cache-stats'],
    queryFn: ragApi.getCacheStats,
    retry: false,
    refetchOnWindowFocus: false,
  })
  const readinessQuery = useQuery({
    queryKey: ['readiness'],
    queryFn: ragApi.getReadiness,
    retry: false,
    refetchOnWindowFocus: false,
  })

  const documents: DocumentListResponse | undefined = documentsQuery.data
  const metrics: MetricsSummary | undefined = metricsQuery.data
  const settings: SystemSettings | undefined = settingsQuery.data
  const cacheStats: CacheStats | undefined = cacheQuery.data
  const documentsError = documentsQuery.error ? getApiErrorMessage(documentsQuery.error) : null
  const metricsError = metricsQuery.error ? getApiErrorMessage(metricsQuery.error) : null
  const settingsError = settingsQuery.error ? getApiErrorMessage(settingsQuery.error) : null
  const cacheError = cacheQuery.error ? getApiErrorMessage(cacheQuery.error) : null
  const readiness: 'checking' | 'ready' | 'unavailable' = readinessQuery.isLoading
    ? 'checking'
    : readinessQuery.isSuccess
      ? 'ready'
      : 'unavailable'
  const readinessError = readinessQuery.error ? getApiErrorMessage(readinessQuery.error) : null
  const loading = documentsQuery.isLoading
  const refreshing =
    documentsQuery.isFetching ||
    metricsQuery.isFetching ||
    settingsQuery.isFetching ||
    cacheQuery.isFetching

  async function refreshDashboard() {
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: ['documents'] }),
      queryClient.invalidateQueries({ queryKey: ['metrics'] }),
      queryClient.invalidateQueries({ queryKey: ['settings'] }),
      queryClient.invalidateQueries({ queryKey: ['cache-stats'] }),
      queryClient.invalidateQueries({ queryKey: ['readiness'] }),
    ])
  }

  async function handleUpload(file: File) {
    setUploading(true)
    setUploadMessage(null)
    setUploadError(null)

    try {
      const uploaded = await ragApi.uploadDocument(file)
      setUploadMessage(`${uploaded.filename} uploaded. Indexing the corpus now…`)

      try {
        const ingest: IngestResponse = await ragApi.ingestDocuments()
        setUploadMessage(
          `${uploaded.filename} uploaded. Indexed ${formatNumber(ingest.documents_ingested)} documents and ${formatNumber(ingest.chunks_indexed)} chunks.`,
        )
      } catch (error) {
        setUploadError(
          `The file was uploaded, but indexing did not finish: ${getApiErrorMessage(error)}`,
        )
      }
    } catch (error) {
      setUploadError(getApiErrorMessage(error))
    } finally {
      await refreshDashboard()
      setUploading(false)
    }
  }

  function requestUpload(file: File) {
    const alreadyExists = documents?.documents.some(
      (document) => document.name.toLowerCase() === file.name.toLowerCase(),
    )
    if (
      alreadyExists &&
      !window.confirm(`"${file.name}" already exists in the corpus. Replace it and re-index?`)
    ) {
      return
    }
    void handleUpload(file)
  }

  async function handleAsk(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    const cleanQuery = query.trim()
    if (cleanQuery.length < 4 || asking) return

    setAsking(true)
    setAskError(null)
    setAnswer(null)
    try {
      setAnswer(await ragApi.ask(cleanQuery))
    } catch (error) {
      setAskError(getApiErrorMessage(error))
    } finally {
      setAsking(false)
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ['metrics'] }),
        queryClient.invalidateQueries({ queryKey: ['cache-stats'] }),
      ])
    }
  }

  const pageTitle =
    page === 'documents' ? 'Documents' : page === 'ask' ? 'Ask your corpus' : 'Metrics & settings'

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <a className="brand" href="/" aria-label="RAG Studio home">
          <span className="brand__mark">
            <BookOpen size={20} />
          </span>
          <span>
            <strong>RAG Studio</strong>
            <small>Local knowledge workspace</small>
          </span>
        </a>

        <div className="sidebar__label">Workspace</div>
        <nav className="main-nav" aria-label="Main navigation">
          <button
            className={`nav-link ${page === 'documents' ? 'is-active' : ''}`}
            type="button"
            onClick={() => setPage('documents')}
          >
            <LayoutDashboard size={18} />
            <span>Documents</span>
            {documents && <span className="nav-count">{documents.total_count}</span>}
          </button>
          <button
            className={`nav-link ${page === 'ask' ? 'is-active' : ''}`}
            type="button"
            onClick={() => setPage('ask')}
          >
            <MessageSquareText size={18} />
            <span>Ask</span>
          </button>
          <button
            className={`nav-link ${page === 'system' ? 'is-active' : ''}`}
            type="button"
            onClick={() => setPage('system')}
          >
            <Settings2 size={18} />
            <span>Metrics & settings</span>
          </button>
        </nav>

        <div className="sidebar__spacer" />
        <div className="local-notice">
          <ShieldAlert size={17} />
          <div>
            <strong>Local development UI</strong>
            <span>
              {settings?.tenant_auth_enabled
                ? 'This UI does not manage bearer tokens.'
                : 'Development-only default tenant; no login required.'}
            </span>
          </div>
        </div>
        <div className="sidebar__footer">
          <span className={`status-dot ${readiness === 'ready' ? 'is-ready' : 'is-offline'}`} />
          <span>{readiness === 'ready' ? 'Backend ready' : readiness === 'checking' ? 'Connecting…' : 'Backend unavailable'}</span>
        </div>
      </aside>

      <main className="main-area">
        <header className="topbar">
          <div className="breadcrumbs">
            <span>Workspace</span>
            <span className="breadcrumb-separator">/</span>
            <strong>{pageTitle}</strong>
          </div>
          <div className="topbar__actions">
            <span className="environment-badge">LOCAL DEV</span>
            <button
              className="icon-button"
              type="button"
              onClick={() => void refreshDashboard()}
              disabled={refreshing}
              aria-label="Refresh workspace data"
              title="Refresh workspace data"
            >
              <RefreshCw size={17} className={refreshing ? 'spin' : ''} />
            </button>
          </div>
        </header>

        <div className="page-content">
          <section className="page-intro">
            <div>
              <p className="eyebrow">Knowledge workspace</p>
              <h1>{settings?.app_name ?? 'RAG Studio'}</h1>
              <p className="page-intro__copy">
                Upload local sources, index your corpus, and ask questions with citations.
              </p>
            </div>
            <div className={`api-status ${readiness === 'ready' ? 'is-ready' : 'is-offline'}`} title={readinessError ?? undefined}>
              <span className="status-dot" />
              {readiness === 'ready' ? 'API ready' : readiness === 'checking' ? 'Checking API' : 'API unavailable'}
            </div>
          </section>

          {readinessError && (
            <div className="notice notice--error" role="status">
              {readinessError}
            </div>
          )}

          {page === 'documents' && (
            <>
              <div className="overview-grid">
                <MetricCard
                  label="Corpus documents"
                  value={loading ? '—' : formatNumber(documents?.total_count ?? 0)}
                  description="Files available in the corpus folder"
                  icon={FileText}
                />
                <MetricCard
                  label="Indexed chunks"
                  value={loading ? '—' : formatNumber(metrics?.indexed_chunks ?? 0)}
                  description="Passages currently reported by Qdrant"
                  icon={Database}
                />
                <MetricCard
                  label="Ask requests"
                  value={loading ? '—' : formatNumber(metrics?.total_requests ?? 0)}
                  description="Bounded SQLite request history for this tenant"
                  icon={Activity}
                />
              </div>
              {metricsError && (
                <div className="notice notice--warning" role="status">
                  Metrics are not available yet: {metricsError}
                </div>
              )}
              <DocumentList
                documents={documents?.documents ?? []}
                loading={loading}
                error={documentsError}
                refreshing={refreshing}
                uploading={uploading}
                uploadMessage={uploadMessage}
                uploadError={uploadError}
                onRefresh={() => void refreshDashboard()}
                onUpload={requestUpload}
              />
            </>
          )}

          {page === 'ask' && (
            <div className="ask-layout">
              <section className="panel ask-panel">
                <div className="panel-heading">
                  <div>
                    <p className="eyebrow">Retrieval</p>
                    <h2>Ask a question</h2>
                    <p className="panel-description">
                      Search the indexed corpus and review the sources used for the answer.
                    </p>
                  </div>
                  <span className="panel-heading__icon" aria-hidden="true">
                    <Sparkles size={20} />
                  </span>
                </div>

                <form className="question-form" onSubmit={handleAsk}>
                  <label htmlFor="question">Your question</label>
                  <textarea
                    id="question"
                    value={query}
                    onChange={(event) => setQuery(event.target.value)}
                    placeholder="For example: What does the corpus say about…?"
                    rows={4}
                    minLength={4}
                    maxLength={2000}
                    required
                  />
                  <div className="question-form__footer">
                    <span>Retrieves up to 5 passages · 4–2000 characters</span>
                    <button className="button button--primary" type="submit" disabled={asking || query.trim().length < 4}>
                      {asking ? <span className="loader loader--small" /> : <Search size={16} />}
                      {asking ? 'Searching…' : 'Ask corpus'}
                    </button>
                  </div>
                </form>

                <div className="prompt-list">
                  <span>Try a question</span>
                  {[
                    'What are the main topics in my documents?',
                    'Summarize the key recommendations.',
                    'Which document contains the most relevant details?',
                  ].map((suggestion) => (
                    <button
                      className="prompt-chip"
                      type="button"
                      key={suggestion}
                      onClick={() => setQuery(suggestion)}
                    >
                      {suggestion}
                      <ArrowUpRight size={14} />
                    </button>
                  ))}
                </div>
              </section>

              {askError && (
                <div className="notice notice--error" role="alert">
                  {askError}
                </div>
              )}
              {asking && (
                <div className="state-card" role="status">
                  <span className="loader" />
                  Searching your indexed documents…
                </div>
              )}
              {answer && <AnswerCard result={answer} />}
              {!answer && !asking && !askError && (
                <div className="ask-empty">
                  <span className="empty-icon" aria-hidden="true">
                    <MessageSquareText size={22} />
                  </span>
                  <strong>Your answer will appear here</strong>
                  <span>Ask a question to see the API status, provider, and cited passages.</span>
                </div>
              )}
            </div>
          )}

          {page === 'system' && (
            <div className="system-layout">
              <section>
                <div className="section-title">
                  <div>
                    <p className="eyebrow">Runtime</p>
                    <h2>API metrics</h2>
                  </div>
                  {refreshing && <span className="muted-label">Refreshing…</span>}
                </div>
                {metricsError ? (
                  <div className="notice notice--error" role="alert">
                    {metricsError}
                  </div>
                ) : (
                  <div className="system-metrics">
                    <MetricCard
                      label="Ask requests"
                      value={loading ? '—' : formatNumber(metrics?.total_requests ?? 0)}
                      description="Bounded request history stored in SQLite"
                      icon={Activity}
                    />
                    <MetricCard
                      label="Average latency"
                      value={loading ? '—' : `${(metrics?.avg_latency_ms ?? 0).toFixed(1)} ms`}
                      description={`P50 ${(metrics?.p50_latency_ms ?? 0).toFixed(1)} ms · P95 ${(metrics?.p95_latency_ms ?? 0).toFixed(1)} ms`}
                      icon={Gauge}
                    />
                    <MetricCard
                      label="Indexed documents"
                      value={loading ? '—' : formatNumber(metrics?.indexed_documents ?? 0)}
                      description={`${formatNumber(metrics?.indexed_chunks ?? 0)} chunks reported`}
                      icon={FileText}
                    />
                    <MetricCard
                      label="Reported cost"
                      value={loading ? '—' : formatCurrency(metrics?.total_cost_usd ?? 0)}
                      description={settings?.llm_provider === 'mock'
                        ? 'Local extractive provider; no external model billing'
                        : 'Calculated from provider-reported token usage'}
                      icon={Zap}
                    />
                    <MetricCard
                      label="Provider tokens"
                      value={`${formatNumber(metrics?.total_input_tokens ?? 0)} / ${formatNumber(metrics?.total_output_tokens ?? 0)}`}
                      description="Input / output in the retained request history"
                      icon={Activity}
                    />
                  </div>
                )}
                <div className="notice notice--info">
                  In local development, requests use the default development tenant. Metrics are stored in
                  SQLite with a bounded history; query text and document contents are not stored.
                </div>
              </section>

              <section>
                <div className="section-title">
                  <div>
                    <p className="eyebrow">Cache</p>
                    <h2>Cache status</h2>
                  </div>
                </div>
                {cacheError ? (
                  <div className="notice notice--error" role="alert">
                    {cacheError}
                  </div>
                ) : (
                  <div className="system-metrics">
                    <MetricCard
                      label="Configured"
                      value={cacheStats ? (cacheStats.enabled ? 'On' : 'Off') : loading ? '—' : 'Unavailable'}
                      description="Configuration reported by the API"
                      icon={Database}
                    />
                    <MetricCard
                      label="Live cache entries"
                      value={loading ? '—' : formatNumber(cacheStats?.total_entries ?? 0)}
                      description="Unexpired entries for the current corpus version"
                      icon={Database}
                    />
                    <MetricCard
                      label="Cache hits"
                      value={loading ? '—' : formatNumber(cacheStats?.hits ?? 0)}
                      description={`${formatNumber(cacheStats?.misses ?? 0)} misses · ${metrics?.cache_hit_rate ?? 0}% hit rate`}
                      icon={Activity}
                    />
                    <MetricCard
                      label="Similarity threshold"
                      value={cacheStats ? cacheStats.threshold.toFixed(2) : '—'}
                      description={`TTL ${formatNumber(cacheStats?.ttl_seconds ?? 0)} seconds`}
                      icon={Gauge}
                    />
                  </div>
                )}
                <div className="notice notice--info">
                  Cache lookup is scoped to this tenant and corpus version. TTL is enforced during lookup; corpus
                  changes and uploads invalidate this tenant's old entries.
                </div>
              </section>

              {settingsError ? (
                <div className="notice notice--error" role="alert">
                  {settingsError}
                </div>
              ) : (
                <section className="panel settings-panel">
                  <div className="panel-heading">
                    <div>
                      <p className="eyebrow">Configuration</p>
                      <h2>{settings?.app_name ?? 'System settings'}</h2>
                    </div>
                    <Settings2 size={20} className="muted-icon" />
                  </div>
                  {settings ? (
                    <div className="settings-grid">
                      <div className="settings-group">
                        <h3>Corpus & retrieval</h3>
                        <SettingRow label="Environment" value={settings.app_env} />
                        <SettingRow label="Tenant auth" value={settings.tenant_auth_enabled ? 'Required' : 'Development-only bypass'} />
                        <SettingRow label="Corpus directory" value={settings.corpus_dir} />
                        <SettingRow label="Corpus version" value={settings.corpus_version} />
                        <SettingRow label="Embedding model" value={settings.embedding_model} />
                        <SettingRow label="Vector dimensions" value={formatNumber(settings.embedding_dimension)} />
                        <SettingRow label="Qdrant collection" value={settings.qdrant_collection} />
                        <SettingRow label="Qdrant local path" value={settings.qdrant_local_path} />
                      </div>
                      <div className="settings-group">
                        <h3>Provider configuration</h3>
                        <SettingRow label="Configured provider" value={settings.llm_provider} />
                        <SettingRow label="Cheap model setting" value={settings.cheap_model} />
                        <SettingRow label="Strong model setting" value={settings.strong_model} />
                        <SettingRow label="Escalation setting" value={settings.escalation_enabled ? 'Enabled' : 'Disabled'} />
                        <SettingRow
                          label="Cheap input / output per 1M"
                          value={`${formatCurrency(settings.cheap_input_price)} / ${formatCurrency(settings.cheap_output_price)}`}
                        />
                        <SettingRow
                          label="Strong input / output per 1M"
                          value={`${formatCurrency(settings.strong_input_price)} / ${formatCurrency(settings.strong_output_price)}`}
                        />
                        <SettingRow label="Log level" value={settings.log_level} />
                      </div>
                    </div>
                  ) : loading ? (
                    <div className="state-card" role="status">
                      <span className="loader" />
                      Loading settings…
                    </div>
                  ) : (
                    <div className="state-card">Settings are not available.</div>
                  )}
                  <div className="notice notice--info">
                    The default provider is local extractive code. When an external provider is explicitly
                    configured, the API routes through its cheap/strong models and calculates cost from reported
                    token usage. Questions and retrieved excerpts are sent to that provider; API keys are never
                    shown here.
                  </div>
                </section>
              )}
            </div>
          )}
        </div>
      </main>
    </div>
  )
}

export default App
