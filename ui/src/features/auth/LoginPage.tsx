/**
 * Login Page - Design System v2
 *
 * SECURITY:
 * - No password stored in state longer than necessary
 * - Form submission uses secure cookie-based auth
 * - Error messages don't reveal if username exists (security best practice)
 *
 * DESIGN:
 * - Tailwind CSS + shadcn/ui components
 * - Grafana/Portainer-inspired dark theme
 * - WCAG 2.1 AA accessible
 *
 * OIDC (v2.3.0):
 * - Shows SSO button when OIDC is enabled
 * - Handles OIDC callback error messages
 */

import { useState, useEffect, type FormEvent } from 'react'
import { LogIn, KeyRound } from 'lucide-react'
import { useSearchParams, useNavigate } from 'react-router-dom'
import { useAuth } from './AuthContext'
import { useOIDCStatus } from '@/hooks/useOIDC'
import { ApiError, apiClient } from '@/lib/api/client'
import { getBasePath } from '@/lib/utils/basePath'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'

function Divider({ label }: { label: string }) {
  return (
    <div className="relative my-4">
      <div className="absolute inset-0 flex items-center">
        <span className="w-full border-t border-border" />
      </div>
      <div className="relative flex justify-center text-xs uppercase">
        <span className="bg-card px-2 text-muted-foreground">{label}</span>
      </div>
    </div>
  )
}

interface LocalLoginFormProps {
  username: string
  setUsername: (v: string) => void
  password: string
  setPassword: (v: string) => void
  error: string | null
  setError: (v: string | null) => void
  isLoading: boolean
  onSubmit: (e: FormEvent) => void
  submitVariant?: 'default' | 'outline'
}

function LocalLoginForm({
  username, setUsername, password, setPassword,
  error, setError, isLoading, onSubmit, submitVariant,
}: LocalLoginFormProps) {
  return (
    <form onSubmit={onSubmit} className="space-y-4">
      <div className="space-y-2">
        <label htmlFor="username" className="text-xs font-medium text-muted-foreground">
          Username
        </label>
        <Input
          id="username"
          data-testid="login-username"
          type="text"
          value={username}
          onChange={(e) => {
            setUsername(e.target.value)
            if (error) setError(null)
          }}
          disabled={isLoading}
          autoComplete="username"
          autoFocus
          placeholder="Enter your username"
        />
      </div>
      <div className="space-y-2">
        <label htmlFor="password" className="text-xs font-medium text-muted-foreground">
          Password
        </label>
        <Input
          id="password"
          data-testid="login-password"
          type="password"
          value={password}
          onChange={(e) => {
            setPassword(e.target.value)
            if (error) setError(null)
          }}
          disabled={isLoading}
          autoComplete="current-password"
          placeholder="Enter your password"
        />
      </div>
      <Button
        type="submit"
        data-testid="login-submit"
        disabled={isLoading}
        variant={submitVariant}
        className="w-full"
        size="lg"
      >
        {isLoading ? (
          <>
            <span className="mr-2 h-4 w-4 animate-spin rounded-full border-2 border-primary-foreground border-t-transparent" />
            Logging in...
          </>
        ) : (
          <>
            <LogIn className="h-4 w-4" />
            Log In
          </>
        )}
      </Button>
    </form>
  )
}

/**
 * Validate redirect URL to prevent open redirect attacks.
 * Only allows relative paths starting with '/'.
 */
function getSafeRedirect(url: string | null): string {
  if (!url) return '/'
  // Only allow relative paths (must start with / and not //)
  if (url.startsWith('/') && !url.startsWith('//')) {
    return url
  }
  return '/'
}

/** Safe OIDC error messages - prevents phishing via arbitrary URL text */
const OIDC_ERROR_MESSAGES: Record<string, string> = {
  access_denied: 'Access was denied by the identity provider.',
  login_failed: 'SSO login failed. Please try again.',
  invalid_state: 'SSO session expired. Please try again.',
  provider_error: 'The identity provider returned an error.',
  no_email: 'No email address was provided by the identity provider.',
  account_disabled: 'Your account has been disabled.',
}

const DEFAULT_OIDC_ERROR = 'SSO authentication failed. Please try again or contact your administrator.'

export function LoginPage() {
  const { login, isLoading } = useAuth()
  const { data: oidcStatus } = useOIDCStatus()
  const [searchParams] = useSearchParams()
  const navigate = useNavigate()
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [showLocalLogin, setShowLocalLogin] = useState(false)

  // Get redirect URL from query params (e.g., /login?redirect=/quick-action?token=xxx)
  const redirectUrl = getSafeRedirect(searchParams.get('redirect'))

  // Check for OIDC error from callback
  const oidcError = searchParams.get('error')
  const oidcErrorMessage = searchParams.get('message')

  useEffect(() => {
    if (oidcError === 'oidc_error' && oidcErrorMessage) {
      setError(OIDC_ERROR_MESSAGES[oidcErrorMessage] || DEFAULT_OIDC_ERROR)
    }
  }, [oidcError, oidcErrorMessage])

  const handleOIDCLogin = () => {
    // Redirect to OIDC authorize endpoint, preserving redirect URL
    const authorizeUrl = new URL(`${getBasePath()}/api/v2/auth/oidc/authorize`, window.location.origin)
    if (redirectUrl) {
      authorizeUrl.searchParams.set('redirect', redirectUrl)
    }
    window.location.href = authorizeUrl.toString()
  }

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault()
    setError(null)

    if (!username.trim() || !password) {
      setError('Please enter both username and password')
      return
    }

    try {
      await login({ username: username.trim(), password })

      // Sync browser timezone to backend on successful login
      const browserTimezoneOffset = -new Date().getTimezoneOffset()
      apiClient.put('/settings', { timezone_offset: browserTimezoneOffset }).catch(err => {
        console.warn('Failed to sync timezone offset:', err)
      })

      navigate(redirectUrl, { replace: true })
    } catch (err) {
      if (err instanceof ApiError) {
        if (err.status === 401) {
          setError('Invalid username or password')
        } else if (err.status === 429) {
          setError('Too many login attempts. Please try again later.')
        } else {
          setError('Login failed. Please try again.')
        }
      } else {
        setError('Connection error. Please check if the backend is running.')
      }
    }
  }

  const formProps = {
    username, setUsername, password, setPassword,
    error, setError, isLoading, onSubmit: handleSubmit,
  }

  return (
    <div className="flex min-h-screen items-center justify-center bg-background p-4">
      <Card className="w-full max-w-md">
        <CardHeader className="space-y-1 text-center">
          <div className="mb-2 flex justify-center">
            <div className="flex h-12 w-12 items-center justify-center rounded-xl bg-primary/10">
              <LogIn className="h-6 w-6 text-primary" />
            </div>
          </div>
          <CardTitle className="text-2xl">DockMon</CardTitle>
          <CardDescription>Docker Container Monitor</CardDescription>
        </CardHeader>

        <CardContent>
          {error && (
            <div
              role="alert"
              className="mb-4 rounded-lg border-l-4 border-danger bg-danger/10 p-3 text-sm text-danger"
            >
              {error}
            </div>
          )}

          {oidcStatus?.enabled && oidcStatus.sso_default ? (
            <>
              {/* SSO-primary layout */}
              <Button
                type="button"
                className="w-full"
                size="lg"
                onClick={handleOIDCLogin}
              >
                <KeyRound className="h-4 w-4" />
                Sign in with SSO
              </Button>

              {!showLocalLogin ? (
                <button
                  type="button"
                  className="mt-4 w-full text-center text-sm text-muted-foreground hover:text-foreground transition-colors"
                  onClick={() => setShowLocalLogin(true)}
                >
                  Sign in with local account
                </button>
              ) : (
                <>
                  <Divider label="local account" />
                  <LocalLoginForm {...formProps} submitVariant="outline" />
                </>
              )}
            </>
          ) : (
            <>
              {/* Default layout: local login primary */}
              <LocalLoginForm {...formProps} />

              {/* OIDC SSO Button (secondary) */}
              {oidcStatus?.enabled && (
                <>
                  <Divider label="or" />
                  <Button
                    type="button"
                    variant="outline"
                    className="w-full"
                    size="lg"
                    onClick={handleOIDCLogin}
                  >
                    <KeyRound className="h-4 w-4" />
                    Sign in with SSO
                  </Button>
                </>
              )}
            </>
          )}
        </CardContent>
      </Card>
    </div>
  )
}
