import {
  Activity,
  ArrowRight,
  BookOpen,
  CheckCircle2,
  CircleHelp,
  Clock3,
  Database,
  FileText,
  Gauge,
  LayoutDashboard,
  LogOut,
  MessageSquareText,
  Moon,
  RefreshCw,
  Settings2,
  ShieldAlert,
  Sparkles,
  Sun,
  UserRound,
  Zap,
} from 'lucide-react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect, useState } from 'react'
import type { FormEvent } from 'react'
import { AnswerCard } from './components/AnswerCard'
import { DocumentList } from './components/DocumentList'
import { MetricCard } from './components/MetricCard'
import { authApi, getApiErrorMessage, ragApi } from './api'
import type {
  AskResponse,
  AuthUser,
  CacheStats,
  DocumentPermission,
  DocumentInfo,
  DocumentListResponse,
  IngestResponse,
  MetricsSummary,
  SystemSettings,
  UserCreateInput,
} from './api'
import './App.css'

type Page = 'dashboard' | 'documents' | 'chat' | 'system' | 'profile' | 'team'
type Theme = 'light' | 'dark'
type MessageStatus = 'loading' | 'answered' | 'failed'

interface ChatMessage {
  id: string
  question: string
  status: MessageStatus
  answer?: AskResponse
  error?: string
}

interface ActivityItem {
  id: string
  title: string
  detail: string
  time: Date
  icon: 'upload' | 'ask'
}

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

function getInitialTheme(): Theme {
  const savedTheme = window.localStorage.getItem('rag-studio-theme')
  if (savedTheme === 'light' || savedTheme === 'dark') return savedTheme
  return window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light'
}

function SettingRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="setting-row">
      <span>{label}</span>
      <strong title={value}>{value}</strong>
    </div>
  )
}

function Workspace({
  user,
  onLogout,
}: {
  user: AuthUser
  onLogout: () => void
}) {
  const queryClient = useQueryClient()
  const [page, setPage] = useState<Page>('dashboard')
  const [theme, setTheme] = useState<Theme>(getInitialTheme)
  const [uploading, setUploading] = useState(false)
  const [uploadProgress, setUploadProgress] = useState<number | null>(null)
  const [uploadMessage, setUploadMessage] = useState<string | null>(null)
  const [uploadError, setUploadError] = useState<string | null>(null)
  const [deleteMessage, setDeleteMessage] = useState<string | null>(null)
  const [deleteError, setDeleteError] = useState<string | null>(null)
  const [deletingFilename, setDeletingFilename] = useState<string | null>(null)
  const [reindexing, setReindexing] = useState(false)
  const [reindexMessage, setReindexMessage] = useState<string | null>(null)
  const [reindexError, setReindexError] = useState<string | null>(null)
  const [query, setQuery] = useState('')
  const [messages, setMessages] = useState<ChatMessage[]>([])
  const [asking, setAsking] = useState(false)
  const [copiedMessageId, setCopiedMessageId] = useState<string | null>(null)
  const [copyError, setCopyError] = useState<string | null>(null)
  const [activity, setActivity] = useState<ActivityItem[]>([])
  const [currentPassword, setCurrentPassword] = useState('')
  const [newPassword, setNewPassword] = useState('')
  const [passwordMessage, setPasswordMessage] = useState<string | null>(null)
  const [passwordError, setPasswordError] = useState<string | null>(null)
  const [newUserEmail, setNewUserEmail] = useState('')
  const [newUserName, setNewUserName] = useState('')
  const [newUserPassword, setNewUserPassword] = useState('')
  const [newUserRole, setNewUserRole] = useState<AuthUser['role']>('EDITOR')
  const [teamMessage, setTeamMessage] = useState<string | null>(null)
  const [teamError, setTeamError] = useState<string | null>(null)
  const [selectedDocument, setSelectedDocument] = useState('')
  const [selectedPermissionUser, setSelectedPermissionUser] = useState('')
  const [permissionCanRead, setPermissionCanRead] = useState(false)
  const [permissionCanEdit, setPermissionCanEdit] = useState(false)

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
    enabled: user.role === 'ADMIN',
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
  const teamUsersQuery = useQuery({
    queryKey: ['team-users'],
    queryFn: authApi.listUsers,
    enabled: user.role === 'ADMIN',
    retry: false,
  })
  const documentPermissionsQuery = useQuery({
    queryKey: ['document-permissions', selectedDocument],
    queryFn: () => authApi.getDocumentPermissions(selectedDocument),
    enabled: user.role === 'ADMIN' && Boolean(selectedDocument),
    retry: false,
  })

  useEffect(() => {
    const permission = documentPermissionsQuery.data?.find(
      (item) => item.user_id === selectedPermissionUser,
    )
    setPermissionCanRead(permission?.can_read ?? false)
    setPermissionCanEdit(permission?.can_edit ?? false)
  }, [documentPermissionsQuery.data, selectedPermissionUser])

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
    cacheQuery.isFetching ||
    readinessQuery.isFetching
  const pageTitle =
    page === 'dashboard'
      ? 'Overview'
      : page === 'documents'
        ? 'Documents'
        : page === 'chat'
          ? 'Ask your corpus'
          : page === 'system'
            ? 'System & settings'
            : page === 'team'
              ? 'Team & access'
              : 'Your profile'

  async function refreshDashboard() {
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: ['documents'] }),
      queryClient.invalidateQueries({ queryKey: ['metrics'] }),
      queryClient.invalidateQueries({ queryKey: ['settings'] }),
      queryClient.invalidateQueries({ queryKey: ['cache-stats'] }),
      queryClient.invalidateQueries({ queryKey: ['readiness'] }),
    ])
  }

  function recordActivity(title: string, detail: string, icon: ActivityItem['icon']) {
    setActivity((current) => [
      { id: crypto.randomUUID(), title, detail, time: new Date(), icon },
      ...current,
    ].slice(0, 6))
  }

  async function handleUpload(file: File) {
    setUploading(true)
    setUploadProgress(0)
    setUploadMessage(null)
    setUploadError(null)
    setDeleteMessage(null)
    setDeleteError(null)

    try {
      const uploaded = await ragApi.uploadDocument(file, setUploadProgress)
      recordActivity('Document uploaded', uploaded.filename, 'upload')
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
      setUploadProgress(null)
      await refreshDashboard()
      setUploading(false)
    }
  }

  async function handleRoleChange(userId: string, role: AuthUser['role']) {
    setTeamMessage(null)
    setTeamError(null)
    try {
      await authApi.updateUserRole(userId, role)
      setTeamMessage('User role updated; their active sessions were revoked.')
      await queryClient.invalidateQueries({ queryKey: ['team-users'] })
    } catch (error) {
      setTeamError(getApiErrorMessage(error))
    }
  }

  async function handleDeactivateUser(userId: string) {
    if (!window.confirm('Deactivate this account and revoke its sessions?')) return
    setTeamMessage(null)
    setTeamError(null)
    try {
      await authApi.deactivateUser(userId)
      setTeamMessage('User deactivated.')
      await queryClient.invalidateQueries({ queryKey: ['team-users'] })
    } catch (error) {
      setTeamError(getApiErrorMessage(error))
    }
  }

  function requestUpload(file: File) {
    if (!/\.(txt|pdf)$/i.test(file.name)) {
      setUploadMessage(null)
      setUploadError('Unsupported file format. Choose a PDF or TXT file.')
      return
    }
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

  async function handleDelete(document: DocumentInfo) {
    if (!window.confirm(`Delete "${document.name}" from this corpus? This cannot be undone.`)) {
      return
    }
    setDeletingFilename(document.name)
    setDeleteMessage(null)
    setDeleteError(null)
    setUploadError(null)

    try {
      const result = await ragApi.deleteDocument(document.name)
      setDeleteMessage(result.message)
      recordActivity('Document deleted', result.filename, 'upload')
      await refreshDashboard()
    } catch (error) {
      setDeleteError(getApiErrorMessage(error))
    } finally {
      setDeletingFilename(null)
    }
  }

  async function handleReindex() {
    setReindexing(true)
    setReindexMessage(null)
    setReindexError(null)
    try {
      const result = await ragApi.ingestDocuments()
      setReindexMessage(
        `Indexed ${formatNumber(result.documents_ingested)} documents and ${formatNumber(result.chunks_indexed)} chunks.`,
      )
      await refreshDashboard()
    } catch (error) {
      setReindexError(getApiErrorMessage(error))
    } finally {
      setReindexing(false)
    }
  }

  async function askQuestion(question: string, messageId: string = crypto.randomUUID()) {
    setAsking(true)
    setCopyError(null)
    setCopiedMessageId(null)
    setMessages((current) => [
      ...current.filter((message) => message.id !== messageId),
      { id: messageId, question, status: 'loading' },
    ])
    try {
      const answer = await ragApi.ask(question)
      setMessages((current) =>
        current.map((message) =>
          message.id === messageId ? { ...message, status: 'answered', answer } : message,
        ),
      )
      recordActivity('Question answered', question, 'ask')
    } catch (error) {
      setMessages((current) =>
        current.map((message) =>
          message.id === messageId
            ? { ...message, status: 'failed', error: getApiErrorMessage(error) }
            : message,
        ),
      )
    } finally {
      setAsking(false)
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ['metrics'] }),
        queryClient.invalidateQueries({ queryKey: ['cache-stats'] }),
      ])
    }
  }

  async function handleAsk(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    const cleanQuery = query.trim()
    if (cleanQuery.length < 4 || asking) return
    setQuery('')
    await askQuestion(cleanQuery)
  }

  async function handleChangePassword(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    setPasswordMessage(null)
    setPasswordError(null)
    try {
      await authApi.changePassword(currentPassword, newPassword)
      setCurrentPassword('')
      setNewPassword('')
      setPasswordMessage('Password changed. Sign in again with your new password.')
      onLogout()
    } catch (error) {
      setPasswordError(getApiErrorMessage(error))
    }
  }

  async function handleCreateUser(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    setTeamMessage(null)
    setTeamError(null)
    try {
      const payload: UserCreateInput = {
        email: newUserEmail,
        display_name: newUserName,
        password: newUserPassword,
        role: newUserRole,
      }
      await authApi.createUser(payload)
      setNewUserEmail('')
      setNewUserName('')
      setNewUserPassword('')
      setTeamMessage('User created in this tenant.')
      await queryClient.invalidateQueries({ queryKey: ['team-users'] })
    } catch (error) {
      setTeamError(getApiErrorMessage(error))
    }
  }

  async function handleSavePermissions() {
    if (!selectedDocument || !selectedPermissionUser) return
    setTeamMessage(null)
    setTeamError(null)
    const permissions: DocumentPermission[] = (
      documentPermissionsQuery.data ?? []
    ).filter((permission) => permission.user_id !== selectedPermissionUser)
    if (permissionCanRead || permissionCanEdit) {
      permissions.push({
        user_id: selectedPermissionUser,
        can_read: permissionCanRead || permissionCanEdit,
        can_edit: permissionCanEdit,
      })
    }
    try {
      await authApi.setDocumentPermissions(selectedDocument, permissions)
      setTeamMessage('Document access updated.')
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ['document-permissions', selectedDocument] }),
        queryClient.invalidateQueries({ queryKey: ['documents'] }),
      ])
    } catch (error) {
      setTeamError(getApiErrorMessage(error))
    }
  }

  async function copyAnswer(messageId: string, answer: string) {
    try {
      await navigator.clipboard.writeText(answer)
      setCopiedMessageId(messageId)
      setCopyError(null)
    } catch {
      setCopyError('Clipboard access is unavailable in this browser. Select and copy the answer text instead.')
    }
  }

  function changeTheme() {
    const nextTheme = theme === 'light' ? 'dark' : 'light'
    setTheme(nextTheme)
    window.localStorage.setItem('rag-studio-theme', nextTheme)
  }

  const navItems: { id: Page; label: string; icon: typeof LayoutDashboard }[] = [
    { id: 'dashboard', label: 'Overview', icon: LayoutDashboard },
    { id: 'documents', label: 'Documents', icon: FileText },
    { id: 'chat', label: 'Ask your corpus', icon: MessageSquareText },
    { id: 'system', label: 'System & settings', icon: Settings2 },
    { id: 'team', label: 'Team & access', icon: UserRound },
  ]

  return (
    <div className="app-shell" data-theme={theme}>
      <aside className="sidebar">
        <a
          className="brand"
          href="/"
          aria-label="RAG Studio home"
          onClick={(event) => {
            event.preventDefault()
            setPage('dashboard')
          }}
        >
          <span className="brand__mark"><BookOpen size={19} /></span>
          <span className="brand__copy">
            <strong>RAG Studio</strong>
            <small>Knowledge workspace</small>
          </span>
        </a>

        <div className="sidebar__label">Workspace</div>
        <nav className="main-nav" aria-label="Main navigation">
          {navItems
            .filter(({ id }) =>
              (id !== 'system' || user.role === 'ADMIN') &&
              (id !== 'team' || user.role === 'ADMIN'),
            )
            .map(({ id, label, icon: Icon }) => (
            <button
              className={`nav-link ${page === id ? 'is-active' : ''}`}
              type="button"
              onClick={() => setPage(id)}
              key={id}
              aria-current={page === id ? 'page' : undefined}
            >
              <Icon size={17} />
              <span>{label}</span>
              {id === 'documents' && documents && (
                <span className="nav-count">{documents.total_count}</span>
              )}
            </button>
            ))}
        </nav>

        <div className="sidebar__spacer" />
        <div className="local-notice">
          <ShieldAlert size={16} aria-hidden="true" />
          <div>
            <strong>{user.role}</strong>
            <span>
              {user.email}
            </span>
          </div>
        </div>
        <button className="sidebar-logout" type="button" onClick={onLogout}>
          <LogOut size={15} /> Sign out
        </button>
        <div className="sidebar__footer">
          <span className={`status-dot ${readiness === 'ready' ? 'is-ready' : readiness === 'unavailable' ? 'is-offline' : ''}`} />
          <span>
            {readiness === 'ready'
              ? 'Backend ready'
              : readiness === 'checking'
                ? 'Connecting to API…'
                : 'Backend unavailable'}
          </span>
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
            <span className="environment-badge">{settings?.app_env ?? 'LOCAL'}</span>
            <button
              className="profile-button"
              type="button"
              onClick={() => setPage('profile')}
              aria-label="Open your profile"
            >
              <UserRound size={15} />
              <span>{user.display_name}</span>
            </button>
            <button
              className="icon-button"
              type="button"
              onClick={changeTheme}
              aria-label={`Switch to ${theme === 'light' ? 'dark' : 'light'} theme`}
              title={`Switch to ${theme === 'light' ? 'dark' : 'light'} theme`}
            >
              {theme === 'light' ? <Moon size={16} /> : <Sun size={16} />}
            </button>
            <button
              className="icon-button"
              type="button"
              onClick={() => void refreshDashboard()}
              disabled={refreshing}
              aria-label="Refresh workspace data"
              title="Refresh workspace data"
            >
              <RefreshCw size={16} className={refreshing ? 'spin' : ''} />
            </button>
          </div>
        </header>

        <div className="page-content">
          {readinessError && (
            <div className="notice notice--error" role="status">{readinessError}</div>
          )}

          {page === 'dashboard' && (
            <div className="dashboard-page">
              <section className="dashboard-hero">
                <div>
                  <p className="eyebrow">Knowledge workspace</p>
                  <h1>Good to see you.</h1>
                  <p className="page-intro__copy">
                    Your documents, retrieval activity, and system status at a glance.
                  </p>
                </div>
                <div className="hero-actions">
                  <button className="button button--secondary" type="button" onClick={() => setPage('documents')}>
                    <FileText size={15} /> Manage documents
                  </button>
                  <button className="button button--primary" type="button" onClick={() => setPage('chat')}>
                    <Sparkles size={15} /> Ask a question
                  </button>
                </div>
              </section>

              {metricsError && (
                <div className="notice notice--warning" role="status">
                  Metrics are not available yet: {metricsError}
                </div>
              )}
              {documentsError && (
                <div className="notice notice--warning" role="status">
                  Document count is not available yet: {documentsError}
                </div>
              )}

              <div className="overview-grid">
                <MetricCard
                  label="Total documents"
                  value={documents ? formatNumber(documents.total_count) : '—'}
                  description="Files in the current tenant corpus"
                  icon={FileText}
                />
                <MetricCard
                  label="Indexed documents"
                  value={metrics ? formatNumber(metrics.indexed_documents) : '—'}
                  description={metrics ? `${formatNumber(metrics.indexed_chunks)} indexed passages` : 'Reported by the RAG service'}
                  icon={Database}
                />
                <MetricCard
                  label="Questions asked"
                  value={metrics ? formatNumber(metrics.total_requests) : '—'}
                  description="Requests in retained metrics history"
                  icon={MessageSquareText}
                />
                <MetricCard
                  label="Cache hit rate"
                  value={metrics ? `${metrics.cache_hit_rate}%` : '—'}
                  description={cacheStats ? `${formatNumber(cacheStats.hits)} hits · ${formatNumber(cacheStats.misses)} misses` : 'Reported by the cache metrics'}
                  icon={Zap}
                />
              </div>

              <div className="dashboard-grid">
                <section className="panel activity-panel">
                  <div className="panel-heading">
                    <div>
                      <p className="eyebrow">This session</p>
                      <h2>Recent activity</h2>
                    </div>
                    <Clock3 size={17} className="muted-icon" />
                  </div>
                  {activity.length === 0 ? (
                    <div className="activity-empty">
                      <span className="empty-icon"><Activity size={20} /></span>
                      <strong>No activity in this session</strong>
                      <span>Uploads and answered questions will appear here.</span>
                    </div>
                  ) : (
                    <ul className="activity-list">
                      {activity.slice(0, 5).map((item) => (
                        <li className="activity-item" key={item.id}>
                          <span className={`activity-item__icon activity-item__icon--${item.icon}`}>
                            {item.icon === 'upload' ? <FileText size={15} /> : <MessageSquareText size={15} />}
                          </span>
                          <span className="activity-item__copy">
                            <strong>{item.title}</strong>
                            <small title={item.detail}>{item.detail}</small>
                          </span>
                          <time>{item.time.toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' })}</time>
                        </li>
                      ))}
                    </ul>
                  )}
                  <p className="panel-footnote">Session-only activity; no activity feed API is available.</p>
                </section>

                <section className="panel health-panel">
                  <div className="panel-heading">
                    <div>
                      <p className="eyebrow">Live configuration</p>
                      <h2>System status</h2>
                    </div>
                    <Activity size={17} className="muted-icon" />
                  </div>
                  <div className="health-list">
                    <div className="health-row">
                      <span className={`health-row__icon ${readiness === 'ready' ? 'is-good' : readiness === 'unavailable' ? 'is-bad' : ''}`}>
                        <CheckCircle2 size={16} />
                      </span>
                      <span><strong>API & vector readiness</strong><small>Combined backend readiness check</small></span>
                      <b className={`health-value ${readiness === 'ready' ? 'is-good' : readiness === 'unavailable' ? 'is-bad' : ''}`}>
                        {readiness === 'ready' ? 'Ready' : readiness === 'checking' ? 'Checking' : 'Unavailable'}
                      </b>
                    </div>
                    <div className="health-row">
                      <span className={`health-row__icon ${cacheStats?.enabled ? 'is-good' : ''}`}><Zap size={16} /></span>
                      <span><strong>Semantic cache</strong><small>{cacheStats ? `${formatNumber(cacheStats.total_entries)} current entries` : cacheError ? 'Status unavailable' : 'Loading status'}</small></span>
                      <b className="health-value">{cacheStats ? (cacheStats.enabled ? 'Enabled' : 'Disabled') : '—'}</b>
                    </div>
                    <div className="health-row">
                      <span className="health-row__icon"><Sparkles size={16} /></span>
                      <span><strong>Answer provider</strong><small>{settings?.llm_provider ? 'Configured by backend' : settingsError ? 'Configuration unavailable' : 'Loading configuration'}</small></span>
                      <b className="health-value">{settings?.llm_provider ?? '—'}</b>
                    </div>
                    <div className="health-row">
                      <span className="health-row__icon"><Database size={16} /></span>
                      <span><strong>Embedding model</strong><small>{settings ? `${formatNumber(settings.embedding_dimension)} dimensions` : 'Backend-reported settings'}</small></span>
                      <b className="health-value health-value--model">{settings?.embedding_model ?? '—'}</b>
                    </div>
                  </div>
                  <button className="text-action" type="button" onClick={() => setPage('system')}>
                    View system details <ArrowRight size={14} />
                  </button>
                </section>
              </div>
            </div>
          )}

          {page === 'documents' && (
            <section className="page-section">
              <div className="page-intro">
                <div>
                  <p className="eyebrow">Knowledge base</p>
                  <h1>Documents</h1>
                  <p className="page-intro__copy">Manage the sources your assistant can retrieve from.</p>
                </div>
                <div className={`api-status ${readiness === 'ready' ? 'is-ready' : readiness === 'unavailable' ? 'is-offline' : ''}`}>
                  <span className="status-dot" />
                  {readiness === 'ready' ? 'API ready' : readiness === 'checking' ? 'Checking API' : 'API unavailable'}
                </div>
              </div>
              <DocumentList
                documents={documents?.documents ?? []}
                canManageDocuments={user.role !== 'VIEWER'}
                loading={loading}
                error={documentsError}
                refreshing={refreshing}
                uploading={uploading}
                uploadProgress={uploadProgress}
                uploadMessage={uploadMessage}
                uploadError={uploadError}
                deleteMessage={deleteMessage}
                deleteError={deleteError}
                deletingFilename={deletingFilename}
                reindexing={reindexing}
                onRefresh={() => void refreshDashboard()}
                onUpload={requestUpload}
                onDelete={(document) => void handleDelete(document)}
                onReindex={() => void handleReindex()}
              />
              {reindexMessage && <div className="notice notice--success" role="status">{reindexMessage}</div>}
              {reindexError && <div className="notice notice--error" role="alert">{reindexError}</div>}
            </section>
          )}

          {page === 'profile' && (
            <section className="page-section">
              <div className="page-intro">
                <div>
                  <p className="eyebrow">Account</p>
                  <h1>Your profile</h1>
                  <p className="page-intro__copy">Manage your account and active session.</p>
                </div>
              </div>
              <section className="panel profile-panel">
                <dl className="profile-details">
                  <div><dt>Name</dt><dd>{user.display_name}</dd></div>
                  <div><dt>Email</dt><dd>{user.email}</dd></div>
                  <div><dt>Role</dt><dd>{user.role}</dd></div>
                  <div><dt>Tenant</dt><dd>{user.tenant_id}</dd></div>
                </dl>
                <form className="profile-password-form" onSubmit={(event) => void handleChangePassword(event)}>
                  <h2>Change password</h2>
                  <label>
                    Current password
                    <input
                      type="password"
                      autoComplete="current-password"
                      value={currentPassword}
                      onChange={(event) => setCurrentPassword(event.target.value)}
                      required
                    />
                  </label>
                  <label>
                    New password
                    <input
                      type="password"
                      autoComplete="new-password"
                      minLength={12}
                      maxLength={128}
                      value={newPassword}
                      onChange={(event) => setNewPassword(event.target.value)}
                      required
                    />
                  </label>
                  {passwordMessage && <div className="notice notice--success" role="status">{passwordMessage}</div>}
                  {passwordError && <div className="notice notice--error" role="alert">{passwordError}</div>}
                  <button className="button button--primary" type="submit">Update password</button>
                </form>
                <button className="button button--secondary" type="button" onClick={onLogout}>Sign out</button>
              </section>
            </section>
          )}

          {page === 'team' && user.role === 'ADMIN' && (
            <section className="page-section">
              <div className="page-intro">
                <div>
                  <p className="eyebrow">Tenant administration</p>
                  <h1>Team & access</h1>
                  <p className="page-intro__copy">Manage tenant accounts and document-level access.</p>
                </div>
              </div>
              {teamMessage && <div className="notice notice--success" role="status">{teamMessage}</div>}
              {teamError && <div className="notice notice--error" role="alert">{teamError}</div>}
              <div className="team-grid">
                <section className="panel team-panel">
                  <h2>Add a team member</h2>
                  <form className="profile-password-form" onSubmit={(event) => void handleCreateUser(event)}>
                    <label>
                      Name
                      <input value={newUserName} onChange={(event) => setNewUserName(event.target.value)} maxLength={120} required />
                    </label>
                    <label>
                      Email
                      <input type="email" value={newUserEmail} onChange={(event) => setNewUserEmail(event.target.value)} maxLength={320} required />
                    </label>
                    <label>
                      Temporary password
                      <input type="password" value={newUserPassword} onChange={(event) => setNewUserPassword(event.target.value)} minLength={12} maxLength={128} required />
                    </label>
                    <label>
                      Role
                      <select value={newUserRole} onChange={(event) => setNewUserRole(event.target.value as AuthUser['role'])}>
                        <option value="EDITOR">Editor</option>
                        <option value="VIEWER">Viewer</option>
                        <option value="ADMIN">Admin</option>
                      </select>
                    </label>
                    <button className="button button--primary" type="submit">Create user</button>
                  </form>
                </section>
                <section className="panel team-panel">
                  <h2>Tenant users</h2>
                  {teamUsersQuery.isLoading ? (
                    <div className="state-card" role="status">Loading users…</div>
                  ) : teamUsersQuery.error ? (
                    <div className="notice notice--error" role="alert">{getApiErrorMessage(teamUsersQuery.error)}</div>
                  ) : (
                    <ul className="team-user-list">
                      {(teamUsersQuery.data ?? []).map((member) => (
                        <li key={member.id}>
                          <span><strong>{member.display_name}</strong><small>{member.email}{member.is_active ? '' : ' · inactive'}</small></span>
                          <select
                            aria-label={`Role for ${member.email}`}
                            value={member.role}
                            disabled={!member.is_active}
                            onChange={(event) => void handleRoleChange(member.id, event.target.value as AuthUser['role'])}
                          >
                            <option value="ADMIN">Admin</option>
                            <option value="EDITOR">Editor</option>
                            <option value="VIEWER">Viewer</option>
                          </select>
                          {member.id !== user.id && member.is_active && (
                            <button className="text-action" type="button" onClick={() => void handleDeactivateUser(member.id)}>
                              Deactivate
                            </button>
                          )}
                        </li>
                      ))}
                    </ul>
                  )}
                </section>
              </div>
              <section className="panel team-panel document-access-panel">
                <h2>Document access</h2>
                <p className="panel-description">Grant read or edit access to active users in this tenant. Owners and admins retain their existing permissions.</p>
                <div className="team-access-controls">
                  <label>
                    Document
                    <select value={selectedDocument} onChange={(event) => setSelectedDocument(event.target.value)}>
                      <option value="">Choose a document</option>
                      {(documents?.documents ?? []).map((document) => (
                        <option key={document.path} value={document.path}>{document.name}</option>
                      ))}
                    </select>
                  </label>
                  <label>
                    User
                    <select value={selectedPermissionUser} onChange={(event) => setSelectedPermissionUser(event.target.value)}>
                      <option value="">Choose a user</option>
                      {(teamUsersQuery.data ?? []).filter((member) => member.is_active && member.id !== user.id).map((member) => (
                        <option key={member.id} value={member.id}>{member.display_name} · {member.role}</option>
                      ))}
                    </select>
                  </label>
                </div>
                {selectedDocument && selectedPermissionUser && (
                  <div className="team-permission-controls">
                    {documentPermissionsQuery.isLoading ? (
                      <span role="status">Loading permissions…</span>
                    ) : (
                      <>
                        <label><input type="checkbox" checked={permissionCanRead} onChange={(event) => { setPermissionCanRead(event.target.checked); if (!event.target.checked) setPermissionCanEdit(false) }} /> Read</label>
                        <label><input type="checkbox" checked={permissionCanEdit} onChange={(event) => { setPermissionCanEdit(event.target.checked); if (event.target.checked) setPermissionCanRead(true) }} /> Edit</label>
                        <button className="button button--secondary" type="button" onClick={() => void handleSavePermissions()} disabled={documentPermissionsQuery.isLoading}>Save access</button>
                      </>
                    )}
                  </div>
                )}
              </section>
            </section>
          )}

          {page === 'chat' && (
            <section className="chat-page">
              <div className="page-intro">
                <div>
                  <p className="eyebrow">Retrieval assistant</p>
                  <h1>Ask your corpus</h1>
                  <p className="page-intro__copy">Get grounded answers with citations from your indexed documents.</p>
                </div>
                {messages.length > 0 && (
                  <button
                    className="button button--secondary"
                    type="button"
                    onClick={() => {
                      setMessages([])
                      setQuery('')
                      setCopyError(null)
                      setCopiedMessageId(null)
                    }}
                    disabled={asking}
                  >
                    Clear conversation
                  </button>
                )}
              </div>

              <div className="chat-shell">
                {messages.length === 0 ? (
                  <div className="chat-welcome">
                    <span className="chat-welcome__icon"><Sparkles size={22} /></span>
                    <h2>What would you like to know?</h2>
                    <p>Answers are grounded in your indexed documents and include source citations.</p>
                    <div className="prompt-list">
                      {[
                        'What are the main topics in my documents?',
                        'Summarize the key recommendations.',
                        'Which sources are most relevant to this topic?',
                      ].map((suggestion) => (
                        <button
                          className="prompt-chip"
                          type="button"
                          key={suggestion}
                          onClick={() => setQuery(suggestion)}
                        >
                          {suggestion}<ArrowRight size={14} />
                        </button>
                      ))}
                    </div>
                  </div>
                ) : (
                  <div className="conversation" aria-live="polite">
                    {messages.map((message) => (
                      <article className="conversation-turn" key={message.id}>
                        <div className="user-message">
                          <span className="user-message__avatar">Y</span>
                          <div><span className="message-label">You</span><p>{message.question}</p></div>
                        </div>
                        {message.status === 'loading' && (
                          <div className="assistant-pending" role="status">
                            <span className="assistant-avatar"><Sparkles size={16} /></span>
                            <span className="loader" /> Searching your indexed documents…
                          </div>
                        )}
                        {message.status === 'failed' && (
                          <div className="assistant-error" role="alert">
                            <span className="assistant-avatar assistant-avatar--error"><CircleHelp size={16} /></span>
                            <div>
                              <strong>Couldn’t complete that request</strong>
                              <p>{message.error}</p>
                              <button
                                className="button button--secondary"
                                type="button"
                                onClick={() => void askQuestion(message.question, message.id)}
                                disabled={asking}
                              >
                                <RefreshCw size={14} /> Retry
                              </button>
                            </div>
                          </div>
                        )}
                        {message.status === 'answered' && message.answer && (
                          <div className="assistant-message">
                            <span className="assistant-avatar"><Sparkles size={16} /></span>
                            <div className="assistant-message__content">
                              <span className="message-label">RAG Studio</span>
                              <AnswerCard
                                result={message.answer}
                                onCopy={() => void copyAnswer(message.id, message.answer!.answer)}
                                copied={copiedMessageId === message.id}
                              />
                            </div>
                          </div>
                        )}
                      </article>
                    ))}
                  </div>
                )}

                {copyError && <div className="notice notice--error" role="alert">{copyError}</div>}
                <form className="chat-composer" onSubmit={(event) => void handleAsk(event)}>
                  <label className="visually-hidden" htmlFor="chat-question">Message your knowledge base</label>
                  <textarea
                    id="chat-question"
                    value={query}
                    onChange={(event) => setQuery(event.target.value)}
                    placeholder="Ask a question about your documents…"
                    rows={2}
                    minLength={4}
                    maxLength={2000}
                    required
                    disabled={asking}
                  />
                  <div className="chat-composer__footer">
                    <span>Up to 2,000 characters · answers use up to 5 passages</span>
                    <button className="button button--primary" type="submit" disabled={asking || query.trim().length < 4}>
                      {asking ? <span className="loader loader--small" /> : <ArrowRight size={16} />}
                      {asking ? 'Searching…' : 'Send'}
                    </button>
                  </div>
                </form>
                <p className="chat-disclaimer">Conversation history stays in this tab and is not saved by the backend.</p>
              </div>
            </section>
          )}

          {page === 'system' && (
            <section className="page-section">
              <div className="page-intro">
                <div>
                  <p className="eyebrow">Operations</p>
                  <h1>System & settings</h1>
                  <p className="page-intro__copy">Runtime metrics and read-only configuration reported by the backend.</p>
                </div>
                <div className={`api-status ${readiness === 'ready' ? 'is-ready' : readiness === 'unavailable' ? 'is-offline' : ''}`}>
                  <span className="status-dot" />
                  {readiness === 'ready' ? 'API ready' : readiness === 'checking' ? 'Checking API' : 'API unavailable'}
                </div>
              </div>

              <div className="system-layout">
                <section>
                  <div className="section-title">
                    <div><p className="eyebrow">Runtime</p><h2>API metrics</h2></div>
                    {refreshing && <span className="muted-label">Refreshing…</span>}
                  </div>
                  {metricsError ? (
                    <div className="notice notice--error" role="alert">{metricsError}</div>
                  ) : (
                    <div className="system-metrics">
                      <MetricCard label="Ask requests" value={metrics ? formatNumber(metrics.total_requests) : '—'} description="Bounded request history stored in SQLite" icon={Activity} />
                      <MetricCard label="Average latency" value={metrics ? `${metrics.avg_latency_ms.toFixed(1)} ms` : '—'} description={metrics ? `P50 ${metrics.p50_latency_ms.toFixed(1)} ms · P95 ${metrics.p95_latency_ms.toFixed(1)} ms` : 'Reported by the metrics API'} icon={Gauge} />
                      <MetricCard label="Indexed documents" value={metrics ? formatNumber(metrics.indexed_documents) : '—'} description={metrics ? `${formatNumber(metrics.indexed_chunks)} chunks reported` : 'Reported by the RAG service'} icon={FileText} />
                      <MetricCard label="Reported cost" value={metrics ? formatCurrency(metrics.total_cost_usd) : '—'} description={settings?.llm_provider === 'mock' ? 'Local extractive provider; no external model billing' : 'Calculated from provider-reported token usage'} icon={Zap} />
                      <MetricCard label="Provider tokens" value={metrics ? `${formatNumber(metrics.total_input_tokens)} / ${formatNumber(metrics.total_output_tokens)}` : '—'} description="Input / output in retained request history" icon={Activity} />
                    </div>
                  )}
                  <div className="notice notice--info">
                    Metrics are tenant-scoped summaries retained in bounded SQLite history; query text and document contents are not stored.
                  </div>
                </section>

                <section>
                  <div className="section-title">
                    <div><p className="eyebrow">Cache</p><h2>Cache status</h2></div>
                  </div>
                  {cacheError ? (
                    <div className="notice notice--error" role="alert">{cacheError}</div>
                  ) : (
                    <div className="system-metrics">
                      <MetricCard label="Configured" value={cacheStats ? (cacheStats.enabled ? 'On' : 'Off') : '—'} description="Configuration reported by the API" icon={Database} />
                      <MetricCard label="Live cache entries" value={cacheStats ? formatNumber(cacheStats.total_entries) : '—'} description="For the current corpus version" icon={Database} />
                      <MetricCard label="Cache hits" value={cacheStats ? formatNumber(cacheStats.hits) : '—'} description={cacheStats ? `${formatNumber(cacheStats.misses)} misses · ${metrics ? `${metrics.cache_hit_rate}% hit rate` : 'hit rate unavailable'}` : 'Reported by cache metrics'} icon={Activity} />
                      <MetricCard label="Similarity threshold" value={cacheStats ? cacheStats.threshold.toFixed(2) : '—'} description={cacheStats ? `TTL ${formatNumber(cacheStats.ttl_seconds)} seconds` : 'Configuration reported by the API'} icon={Gauge} />
                    </div>
                  )}
                  <div className="notice notice--info">
                    Cache lookup is scoped to this tenant and corpus version. Uploads and corpus changes invalidate stale entries.
                  </div>
                </section>

                {settingsError ? (
                  <div className="notice notice--error" role="alert">{settingsError}</div>
                ) : (
                  <section className="panel settings-panel">
                    <div className="panel-heading">
                      <div><p className="eyebrow">Configuration</p><h2>{settings?.app_name ?? 'System settings'}</h2></div>
                      <Settings2 size={19} className="muted-icon" />
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
                          <SettingRow label="Cheap input / output per 1M" value={`${formatCurrency(settings.cheap_input_price)} / ${formatCurrency(settings.cheap_output_price)}`} />
                          <SettingRow label="Strong input / output per 1M" value={`${formatCurrency(settings.strong_input_price)} / ${formatCurrency(settings.strong_output_price)}`} />
                          <SettingRow label="Log level" value={settings.log_level} />
                        </div>
                      </div>
                    ) : loading ? (
                      <div className="state-card" role="status"><span className="loader" />Loading settings…</div>
                    ) : (
                      <div className="state-card">Settings are not available.</div>
                    )}
                    <div className="notice notice--info">
                      Settings are read-only in this frontend. Provider credentials are never returned or displayed; configure providers in the backend environment.
                    </div>
                  </section>
                )}

                <div className="notice notice--warning auth-notice">
                  <ShieldAlert size={17} />
                  <span>
                    Your account is protected by secure, HttpOnly session cookies. The API enforces role and document permissions.
                  </span>
                </div>
              </div>
            </section>
          )}
        </div>
      </main>
    </div>
  )
}

function AuthPage({ onAuthenticated }: { onAuthenticated: (user: AuthUser) => void }) {
  const [registering, setRegistering] = useState(false)
  const [email, setEmail] = useState('')
  const [displayName, setDisplayName] = useState('')
  const [tenantName, setTenantName] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [submitting, setSubmitting] = useState(false)

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    setError(null)
    setSubmitting(true)
    try {
      const user = registering
        ? await authApi.register({
            email,
            display_name: displayName,
            tenant_name: tenantName,
            password,
          })
        : await authApi.login(email, password)
      onAuthenticated(user)
    } catch (requestError) {
      setError(getApiErrorMessage(requestError))
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <main className="auth-page">
      <section className="auth-card">
        <div className="auth-brand"><BookOpen size={20} /><span>RAG Studio</span></div>
        <p className="eyebrow">{registering ? 'Create workspace' : 'Welcome back'}</p>
        <h1>{registering ? 'Create your account' : 'Sign in'}</h1>
        <p className="page-intro__copy">
          {registering
            ? 'Your account starts a new private tenant workspace.'
            : 'Sign in to access your tenant workspace.'}
        </p>
        <form className="auth-form" onSubmit={(event) => void submit(event)}>
          {registering && (
            <>
              <label>
                Your name
                <input
                  type="text"
                  autoComplete="name"
                  maxLength={120}
                  value={displayName}
                  onChange={(event) => setDisplayName(event.target.value)}
                  required
                />
              </label>
              <label>
                Workspace name
                <input
                  type="text"
                  maxLength={120}
                  value={tenantName}
                  onChange={(event) => setTenantName(event.target.value)}
                  required
                />
              </label>
            </>
          )}
          <label>
            Email
            <input
              type="email"
              autoComplete="email"
              maxLength={320}
              value={email}
              onChange={(event) => setEmail(event.target.value)}
              required
            />
          </label>
          <label>
            Password
            <input
              type="password"
              autoComplete={registering ? 'new-password' : 'current-password'}
              minLength={registering ? 12 : undefined}
              maxLength={128}
              value={password}
              onChange={(event) => setPassword(event.target.value)}
              required
            />
            {registering && <small>Use at least 12 characters.</small>}
          </label>
          {error && <div className="notice notice--error" role="alert">{error}</div>}
          <button className="button button--primary auth-submit" type="submit" disabled={submitting}>
            {submitting ? 'Please wait…' : registering ? 'Create private workspace' : 'Sign in'}
          </button>
        </form>
        <p className="auth-switch">
          {registering ? 'Already have an account?' : 'New to RAG Studio?'}
          {' '}
          <button
            type="button"
            onClick={() => {
              setError(null)
              setRegistering(!registering)
            }}
          >
            {registering ? 'Sign in' : 'Create an account'}
          </button>
        </p>
      </section>
    </main>
  )
}

function App() {
  const queryClient = useQueryClient()
  const userQuery = useQuery<AuthUser | null>({
    queryKey: ['auth-user'],
    queryFn: async () => authApi.me(),
    retry: false,
    refetchOnWindowFocus: false,
  })

  useEffect(() => {
    const handleExpired = () => queryClient.setQueryData(['auth-user'], null)
    window.addEventListener('rag-session-expired', handleExpired)
    return () => window.removeEventListener('rag-session-expired', handleExpired)
  }, [queryClient])

  if (userQuery.isLoading) {
    return <main className="auth-page"><div className="state-card"><span className="loader" />Checking session…</div></main>
  }
  if (userQuery.data) {
    return (
      <Workspace
        user={userQuery.data}
        onLogout={() => {
          void authApi.logout().catch(() => undefined).finally(() => {
            queryClient.clear()
            queryClient.setQueryData(['auth-user'], null)
          })
        }}
      />
    )
  }
  const authStatus = (
    userQuery.error as { response?: { status?: number } } | null
  )?.response?.status
  if (userQuery.error && authStatus !== 401) {
    return (
      <main className="auth-page">
        <section className="auth-card">
          <h1>Unable to reach the authentication service</h1>
          <p className="page-intro__copy">{getApiErrorMessage(userQuery.error)}</p>
          <button className="button button--primary" type="button" onClick={() => void userQuery.refetch()}>
            Try again
          </button>
        </section>
      </main>
    )
  }
  return (
    <AuthPage
      onAuthenticated={(user) => {
        queryClient.setQueryData(['auth-user'], user)
      }}
    />
  )
}

export default App
