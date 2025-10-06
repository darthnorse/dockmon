/**
 * App Component Tests
 * Tests routing and protected route logic
 */

import { describe, it, expect, beforeEach, vi } from 'vitest'
import { screen, waitFor } from '@testing-library/react'
import { render } from '@/test/utils'
import { App } from './App'
import { authApi } from '@/features/auth/api'

// Mock the auth API
vi.mock('@/features/auth/api', () => ({
  authApi: {
    login: vi.fn(),
    logout: vi.fn(),
    getCurrentUser: vi.fn(),
  },
}))

describe('App', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  describe('routing', () => {
    it('should redirect to login when not authenticated', async () => {
      vi.mocked(authApi.getCurrentUser).mockRejectedValue(
        new Error('Unauthorized')
      )

      render(<App />)

      await waitFor(() => {
        expect(screen.getByRole('heading', { name: /dockmon/i })).toBeInTheDocument()
        expect(screen.getByLabelText(/username/i)).toBeInTheDocument()
      })
    })

    it('should show dashboard when authenticated', async () => {
      vi.mocked(authApi.getCurrentUser).mockResolvedValue({
        user: { id: 1, username: 'testuser' },
      })

      render(<App />)

      await waitFor(() => {
        expect(screen.getByText(/dockmon dashboard/i)).toBeInTheDocument()
        expect(screen.getByText(/welcome, testuser/i)).toBeInTheDocument()
      })
    })

    it('should redirect from login to dashboard when already authenticated', async () => {
      vi.mocked(authApi.getCurrentUser).mockResolvedValue({
        user: { id: 1, username: 'testuser' },
      })

      // Manually navigate to /login
      window.history.pushState({}, '', '/login')

      render(<App />)

      await waitFor(() => {
        // Should be redirected to dashboard
        expect(screen.getByText(/dockmon dashboard/i)).toBeInTheDocument()
        expect(window.location.pathname).toBe('/')
      })
    })

    it('should handle unknown routes by redirecting to home', async () => {
      vi.mocked(authApi.getCurrentUser).mockResolvedValue({
        user: { id: 1, username: 'testuser' },
      })

      // Navigate to unknown route
      window.history.pushState({}, '', '/unknown-route')

      render(<App />)

      await waitFor(() => {
        // Should redirect to dashboard (home)
        expect(screen.getByText(/dockmon dashboard/i)).toBeInTheDocument()
        expect(window.location.pathname).toBe('/')
      })
    })
  })

  describe('protected routes', () => {
    it('should protect dashboard route', async () => {
      vi.mocked(authApi.getCurrentUser).mockRejectedValue(
        new Error('Unauthorized')
      )

      // Try to access dashboard directly
      window.history.pushState({}, '', '/')

      render(<App />)

      await waitFor(() => {
        // Should be redirected to login
        expect(screen.getByLabelText(/username/i)).toBeInTheDocument()
        expect(window.location.pathname).toBe('/login')
      })
    })

    it('should show loading state while checking authentication', () => {
      vi.mocked(authApi.getCurrentUser).mockImplementation(
        () => new Promise(() => {}) // Never resolves
      )

      render(<App />)

      expect(screen.getByText(/loading/i)).toBeInTheDocument()
    })
  })
})
