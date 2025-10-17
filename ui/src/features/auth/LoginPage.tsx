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
 */

import { useState, type FormEvent } from 'react'
import { LogIn } from 'lucide-react'
import { useAuth } from './AuthContext'
import { ApiError, apiClient } from '@/lib/api/client'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'

export function LoginPage() {
  const { login, isLoading } = useAuth()
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState<string | null>(null)

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

      // On success, AuthContext will handle navigation
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
        </CardContent>
      </Card>
    </div>
  )
}
