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
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'

export function LoginPage() {
  const { login, isLoading } = useAuth()
  const { data: oidcStatus } = useOIDCStatus()
  const [searchParams] = useSearchParams()
  const navigate = useNavigate()
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState<string | null>(null)

  // Get redirect URL from query params (e.g., /login?redirect=/quick-action?token=xxx)
  const redirectUrl = searchParams.get('redirect')

  // Check for OIDC error from callback
  const oidcError = searchParams.get('error')
  const oidcErrorMessage = searchParams.get('message')

  useEffect(() => {
    if (oidcError === 'oidc_error' && oidcErrorMessage) {
      setError(`SSO Error: ${decodeURIComponent(oidcErrorMessage.replace(/\+/g, ' '))}`)
    }
  }, [oidcError, oidcErrorMessage])

  const handleOIDCLogin = () => {
    // Redirect to OIDC authorize endpoint, preserving redirect URL
    const authorizeUrl = new URL('/api/v2/auth/oidc/authorize', window.location.origin)
    if (redirectUrl) {
      authorizeUrl.searchParams.set('redirect', redirectUrl)
    }
    window.location.href = authorizeUrl.toString()
  }

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault()
    setError(null)

    // Basic client-side validation
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

      // Navigate to redirect URL or home
      navigate(redirectUrl || '/', { replace: true })
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
          <form onSubmit={handleSubmit} className="space-y-4">
            {/* Error Alert */}
            {error && (
              <div
                role="alert"
                className="rounded-lg border-l-4 border-danger bg-danger/10 p-3 text-sm text-danger"
              >
                {error}
              </div>
            )}

            {/* Username Field */}
            <div className="space-y-2">
              <label
                htmlFor="username"
                className="text-xs font-medium text-muted-foreground"
              >
                Username
              </label>
              <Input
                id="username"
                data-testid="login-username"
                type="text"
                value={username}
                onChange={(e) => {
                  setUsername(e.target.value)
                  if (error) setError(null) // Clear error when typing
                }}
                disabled={isLoading}
                autoComplete="username"
                autoFocus
                placeholder="Enter your username"
              />
            </div>

            {/* Password Field */}
            <div className="space-y-2">
              <label
                htmlFor="password"
                className="text-xs font-medium text-muted-foreground"
              >
                Password
              </label>
              <Input
                id="password"
                data-testid="login-password"
                type="password"
                value={password}
                onChange={(e) => {
                  setPassword(e.target.value)
                  if (error) setError(null) // Clear error when typing
                }}
                disabled={isLoading}
                autoComplete="current-password"
                placeholder="Enter your password"
              />
            </div>

            {/* Submit Button */}
            <Button
              type="submit"
              data-testid="login-submit"
              disabled={isLoading}
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

          {/* OIDC SSO Button */}
          {oidcStatus?.enabled && (
            <>
              <div className="relative my-4">
                <div className="absolute inset-0 flex items-center">
                  <span className="w-full border-t border-border" />
                </div>
                <div className="relative flex justify-center text-xs uppercase">
                  <span className="bg-card px-2 text-muted-foreground">or</span>
                </div>
              </div>

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
        </CardContent>
      </Card>
    </div>
  )
}
