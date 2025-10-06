/**
 * Login Page
 *
 * SECURITY:
 * - No password stored in state longer than necessary
 * - Form submission uses secure cookie-based auth
 * - Error messages don't reveal if username exists (security best practice)
 */

import { useState, type FormEvent } from 'react'
import { useAuth } from './AuthContext'
import { ApiError } from '@/lib/api/client'

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
    <div style={styles.container}>
      <div style={styles.card}>
        <h1 style={styles.title}>DockMon</h1>
        <p style={styles.subtitle}>Docker Container Monitor</p>

        <form onSubmit={handleSubmit} style={styles.form}>
          {error && (
            <div style={styles.error} role="alert">
              {error}
            </div>
          )}

          <div style={styles.fieldGroup}>
            <label htmlFor="username" style={styles.label}>
              Username
            </label>
            <input
              id="username"
              type="text"
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              disabled={isLoading}
              autoComplete="username"
              autoFocus
              required
              style={styles.input}
            />
          </div>

          <div style={styles.fieldGroup}>
            <label htmlFor="password" style={styles.label}>
              Password
            </label>
            <input
              id="password"
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              disabled={isLoading}
              autoComplete="current-password"
              required
              style={styles.input}
            />
          </div>

          <button
            type="submit"
            disabled={isLoading}
            style={{
              ...styles.button,
              ...(isLoading ? styles.buttonDisabled : {}),
            }}
          >
            {isLoading ? 'Logging in...' : 'Log In'}
          </button>
        </form>

        <p style={styles.footer}>
          Default credentials: <code style={styles.code}>admin</code> /{' '}
          <code style={styles.code}>dockmon123</code>
        </p>
      </div>
    </div>
  )
}

// Inline styles for Phase 2 MVP (will be replaced with CSS/Tailwind later)
const styles = {
  container: {
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
    minHeight: '100vh',
    backgroundColor: '#0f172a',
  },
  card: {
    width: '100%',
    maxWidth: '400px',
    padding: '2rem',
    backgroundColor: '#1e293b',
    borderRadius: '0.5rem',
    boxShadow: '0 10px 25px rgba(0, 0, 0, 0.5)',
  },
  title: {
    fontSize: '2rem',
    fontWeight: 'bold',
    color: '#f8fafc',
    margin: 0,
    marginBottom: '0.5rem',
    textAlign: 'center' as const,
  },
  subtitle: {
    fontSize: '0.875rem',
    color: '#94a3b8',
    margin: 0,
    marginBottom: '2rem',
    textAlign: 'center' as const,
  },
  form: {
    display: 'flex',
    flexDirection: 'column' as const,
    gap: '1rem',
  },
  error: {
    padding: '0.75rem',
    backgroundColor: '#7f1d1d',
    border: '1px solid #991b1b',
    borderRadius: '0.25rem',
    color: '#fecaca',
    fontSize: '0.875rem',
  },
  fieldGroup: {
    display: 'flex',
    flexDirection: 'column' as const,
    gap: '0.5rem',
  },
  label: {
    fontSize: '0.875rem',
    fontWeight: '500',
    color: '#e2e8f0',
  },
  input: {
    padding: '0.75rem',
    backgroundColor: '#334155',
    border: '1px solid #475569',
    borderRadius: '0.25rem',
    color: '#f8fafc',
    fontSize: '1rem',
  },
  button: {
    padding: '0.75rem',
    backgroundColor: '#3b82f6',
    border: 'none',
    borderRadius: '0.25rem',
    color: '#ffffff',
    fontSize: '1rem',
    fontWeight: '500',
    cursor: 'pointer',
    marginTop: '0.5rem',
  },
  buttonDisabled: {
    opacity: 0.5,
    cursor: 'not-allowed',
  },
  footer: {
    marginTop: '1.5rem',
    fontSize: '0.75rem',
    color: '#64748b',
    textAlign: 'center' as const,
  },
  code: {
    padding: '0.125rem 0.25rem',
    backgroundColor: '#334155',
    borderRadius: '0.125rem',
    fontFamily: 'monospace',
    color: '#94a3b8',
  },
}
