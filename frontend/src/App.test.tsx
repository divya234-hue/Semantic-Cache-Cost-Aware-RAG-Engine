import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import App from './App'
import { authApi, ragApi } from './api'
import type { AuthUser } from './api'

const mocks = vi.hoisted(() => ({
  auth: {
    me: vi.fn(),
    login: vi.fn(),
    register: vi.fn(),
    logout: vi.fn(),
    changePassword: vi.fn(),
    listUsers: vi.fn(),
    createUser: vi.fn(),
    updateUserRole: vi.fn(),
    deactivateUser: vi.fn(),
    getDocumentPermissions: vi.fn(),
    setDocumentPermissions: vi.fn(),
  },
  rag: {
    listDocuments: vi.fn(),
    getMetrics: vi.fn(),
    getSettings: vi.fn(),
    getCacheStats: vi.fn(),
    getReadiness: vi.fn(),
  },
}))

vi.mock('./api', () => ({
  authApi: mocks.auth,
  ragApi: mocks.rag,
  getApiErrorMessage: (error: unknown) =>
    error instanceof Error ? error.message : 'Request failed',
}))

const viewer: AuthUser = {
  id: 'user-viewer',
  email: 'viewer@example.com',
  display_name: 'Viewer Account',
  tenant_id: 'tenant-viewer',
  role: 'VIEWER',
  is_active: true,
}

function renderApp() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  })
  return render(
    <QueryClientProvider client={queryClient}>
      <App />
    </QueryClientProvider>,
  )
}

describe('authentication UI', () => {
  beforeEach(() => {
    window.localStorage.clear()
    vi.stubGlobal(
      'matchMedia',
      vi.fn().mockReturnValue({
        matches: false,
        addEventListener: vi.fn(),
        removeEventListener: vi.fn(),
      }),
    )
    vi.mocked(ragApi.listDocuments).mockResolvedValue({
      documents: [],
      total_count: 0,
      corpus_dir: '/tenant/documents',
    })
    vi.mocked(ragApi.getMetrics).mockResolvedValue({
      total_requests: 0,
      cache_hit_count: 0,
      cache_miss_count: 0,
      cache_hit_rate: 0,
      avg_latency_ms: 0,
      p50_latency_ms: 0,
      p95_latency_ms: 0,
      total_cost_usd: 0,
      cheap_route_count: 0,
      strong_route_count: 0,
      escalated_count: 0,
      total_input_tokens: 0,
      total_output_tokens: 0,
      indexed_documents: 0,
      indexed_chunks: 0,
    })
    vi.mocked(ragApi.getCacheStats).mockResolvedValue({
      enabled: true,
      threshold: 0.9,
      ttl_seconds: 120,
      total_entries: 0,
      hits: 0,
      misses: 0,
      corpus_version: 'version-1',
    })
    vi.mocked(ragApi.getReadiness).mockResolvedValue({ status: 'ready' })
  })

  afterEach(() => {
    cleanup()
    vi.unstubAllGlobals()
  })

  it('shows sign-in instead of workspace content without a valid session', async () => {
    vi.mocked(authApi.me).mockRejectedValue({ response: { status: 401 } })

    renderApp()

    expect(await screen.findByRole('heading', { name: 'Sign in' })).toBeTruthy()
    expect(screen.queryByRole('navigation', { name: 'Main navigation' })).toBeNull()
  })

  it('logs in and hides admin navigation for a viewer', async () => {
    vi.mocked(authApi.me).mockRejectedValueOnce({ response: { status: 401 } })
    vi.mocked(authApi.login).mockResolvedValue(viewer)

    renderApp()
    fireEvent.change(await screen.findByLabelText('Email'), {
      target: { value: viewer.email },
    })
    fireEvent.change(screen.getByLabelText(/Password/), {
      target: { value: 'viewer-account-long-password' },
    })
    fireEvent.click(screen.getByRole('button', { name: 'Sign in' }))

    expect(await screen.findByRole('button', { name: 'Overview' })).toBeTruthy()
    expect(screen.getByText('VIEWER')).toBeTruthy()
    expect(screen.queryByRole('button', { name: 'Team & access' })).toBeNull()
    expect(screen.queryByRole('button', { name: 'System & settings' })).toBeNull()
  })

  it('creates an account and tenant from the registration form', async () => {
    const admin: AuthUser = { ...viewer, role: 'ADMIN' }
    vi.mocked(authApi.me).mockRejectedValueOnce({ response: { status: 401 } })
    vi.mocked(authApi.register).mockResolvedValue(admin)

    renderApp()
    fireEvent.click(await screen.findByRole('button', { name: 'Create an account' }))
    fireEvent.change(screen.getByLabelText('Your name'), {
      target: { value: admin.display_name },
    })
    fireEvent.change(screen.getByLabelText('Workspace name'), {
      target: { value: 'Private workspace' },
    })
    fireEvent.change(screen.getByLabelText('Email'), {
      target: { value: admin.email },
    })
    fireEvent.change(screen.getByLabelText(/Password/), {
      target: { value: 'administrator-account-long-password' },
    })
    fireEvent.click(screen.getByRole('button', { name: 'Create private workspace' }))

    expect(await screen.findByText('ADMIN')).toBeTruthy()
    expect(authApi.register).toHaveBeenCalledWith({
      email: admin.email,
      display_name: admin.display_name,
      tenant_name: 'Private workspace',
      password: 'administrator-account-long-password',
    })
  })

  it('shows the authentication error when login fails', async () => {
    vi.mocked(authApi.me).mockRejectedValueOnce({ response: { status: 401 } })
    vi.mocked(authApi.login).mockRejectedValue(new Error('Invalid email or password.'))

    renderApp()
    fireEvent.change(await screen.findByLabelText('Email'), {
      target: { value: viewer.email },
    })
    fireEvent.change(screen.getByLabelText('Password'), {
      target: { value: 'incorrect-password' },
    })
    fireEvent.click(screen.getByRole('button', { name: 'Sign in' }))

    expect((await screen.findByRole('alert')).textContent).toContain(
      'Invalid email or password.',
    )
    await waitFor(() => expect(authApi.login).toHaveBeenCalledOnce())
  })

  it('returns to sign-in when the session-expired event is received', async () => {
    vi.mocked(authApi.me).mockResolvedValue(viewer)

    renderApp()
    expect(await screen.findByRole('button', { name: 'Overview' })).toBeTruthy()
    window.dispatchEvent(new Event('rag-session-expired'))

    expect(await screen.findByRole('heading', { name: 'Sign in' })).toBeTruthy()
  })
})
