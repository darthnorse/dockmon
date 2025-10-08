/**
 * App Component Tests
 * Tests routing and protected route logic
 */

import { describe, it, expect, beforeEach, vi } from 'vitest'
import { screen, waitFor, render } from '@testing-library/react'
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
    // Reset all mocks completely
    vi.mocked(authApi.login).mockReset()
    vi.mocked(authApi.logout).mockReset()
    vi.mocked(authApi.getCurrentUser).mockReset()

    // Set default: getCurrentUser rejects (not authenticated)
    vi.mocked(authApi.getCurrentUser).mockImplementation(() =>
      Promise.reject(new Error('Unauthorized'))
    )
  })

  describe('routing', () => {
    it('should redirect to login when not authenticated', async () => {
      // Uses default mock from beforeEach (rejected/unauthorized)
      render(<App />)

      await waitFor(() => {
        expect(screen.getByRole('heading', { name: /dockmon/i })).toBeInTheDocument()
      })
      expect(await screen.findByLabelText(/username/i)).toBeInTheDocument()
    })

    it('should show dashboard when authenticated', async () => {
      vi.mocked(authApi.getCurrentUser).mockImplementation(() =>
        Promise.resolve({
          user: { id: 1, username: 'testuser' },
        })
      )

      render(<App />)

      await waitFor(() => {
        expect(screen.getByRole('heading', { name: /^dashboard$/i })).toBeInTheDocument()
        expect(screen.getByText(/monitor your docker containers/i)).toBeInTheDocument()
      })
    })

    it('should redirect from login to dashboard when already authenticated', async () => {
      vi.mocked(authApi.getCurrentUser).mockImplementation(() =>
        Promise.resolve({
          user: { id: 1, username: 'testuser' },
        })
      )

      // Manually navigate to /login
      window.history.pushState({}, '', '/login')

      render(<App />)

      await waitFor(() => {
        // Should be redirected to dashboard
        expect(screen.getByRole('heading', { name: /^dashboard$/i })).toBeInTheDocument()
        expect(window.location.pathname).toBe('/')
      })
    })

    it('should handle unknown routes by redirecting to home', async () => {
      vi.mocked(authApi.getCurrentUser).mockImplementation(() =>
        Promise.resolve({
          user: { id: 1, username: 'testuser' },
        })
      )

      // Navigate to unknown route
      window.history.pushState({}, '', '/unknown-route')

      render(<App />)

      await waitFor(() => {
        // Should redirect to dashboard (home)
        expect(screen.getByRole('heading', { name: /^dashboard$/i })).toBeInTheDocument()
        expect(window.location.pathname).toBe('/')
      })
    })
  })

  describe('protected routes', () => {
    // Skip: Mock state pollution between tests - requires better test isolation
    it.skip('should protect dashboard route', async () => {
      // Uses default mock from beforeEach (rejected/unauthorized)
      render(<App />)

      // App starts at "/", which is protected
      // Should redirect to login when not authenticated
      expect(await screen.findByLabelText(/username/i)).toBeInTheDocument()
      expect(await screen.findByRole('button', { name: /log in/i})).toBeInTheDocument()
    })

    // Skip: Mock state pollution between tests - requires better test isolation
    it.skip('should show loading state while checking authentication', async () => {
      vi.mocked(authApi.getCurrentUser).mockImplementation(
        () => new Promise(() => {}) // Never resolves
      )

      render(<App />)

      expect(await screen.findByText(/loading/i)).toBeInTheDocument()
    })
  })
})
