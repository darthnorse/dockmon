/**
 * LoginPage — OIDC status loading guard
 *
 * Regression cover for the logout flash: while the OIDC status is still loading,
 * LoginPage must NOT default to the local username/password form (that briefly
 * shows the wrong UI for SSO-only setups). It shows a neutral loading state, and
 * only falls back to the local form once the status query settles (incl. error).
 */

import { describe, it, expect, beforeEach, vi } from 'vitest'
import { screen } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render } from '@/test/utils'
import { LoginPage } from './LoginPage'
import { AuthProvider } from './AuthContext'
import { authApi } from './api'
import { useOIDCStatus } from '@/hooks/useOIDC'
import type { OIDCStatus } from '@/types/oidc'

vi.mock('./api', () => ({
  authApi: {
    login: vi.fn(),
    logout: vi.fn(),
    getCurrentUser: vi.fn(),
  },
}))

vi.mock('@/hooks/useOIDC', () => ({
  useOIDCStatus: vi.fn(),
}))

type StatusResult = ReturnType<typeof useOIDCStatus>

function statusResult(over: Partial<StatusResult>): StatusResult {
  return {
    data: undefined,
    isLoading: false,
    isError: false,
    ...over,
  } as unknown as StatusResult
}

describe('LoginPage — OIDC status loading guard', () => {
  let queryClient: QueryClient

  beforeEach(() => {
    queryClient = new QueryClient({
      defaultOptions: {
        queries: { retry: false },
        mutations: { retry: false },
      },
    })
    vi.clearAllMocks()
    vi.mocked(authApi.getCurrentUser).mockRejectedValue(new Error('Unauthorized'))
  })

  const renderLoginPage = () =>
    render(
      <QueryClientProvider client={queryClient}>
        <AuthProvider>
          <LoginPage />
        </AuthProvider>
      </QueryClientProvider>
    )

  it('shows a loading state (not the local form) while OIDC status is loading', async () => {
    vi.mocked(useOIDCStatus).mockReturnValue(statusResult({ isLoading: true }))

    renderLoginPage()

    expect(await screen.findByTestId('login-loading')).toBeInTheDocument()
    expect(screen.queryByLabelText(/username/i)).not.toBeInTheDocument()
    expect(screen.queryByLabelText(/password/i)).not.toBeInTheDocument()
  })

  it('falls back to the local form if OIDC status fails to load', async () => {
    vi.mocked(useOIDCStatus).mockReturnValue(statusResult({ isError: true }))

    renderLoginPage()

    expect(await screen.findByLabelText(/username/i)).toBeInTheDocument()
    expect(screen.queryByTestId('login-loading')).not.toBeInTheDocument()
  })

  it('shows the SSO-only view (no local form) once status says local login is disabled', async () => {
    vi.mocked(useOIDCStatus).mockReturnValue(
      statusResult({
        data: {
          enabled: true,
          provider_configured: true,
          sso_default: false,
          local_login_disabled: true,
          local_login_env_override: false,
        } as OIDCStatus,
      })
    )

    renderLoginPage()

    expect(
      await screen.findByRole('button', { name: /sign in with sso/i })
    ).toBeInTheDocument()
    expect(screen.queryByLabelText(/username/i)).not.toBeInTheDocument()
  })
})
