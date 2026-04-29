/**
 * App Component Tests
 * Tests routing and protected route logic
 */

import { describe, it, expect, beforeEach, vi } from 'vitest'
import { screen, waitFor, render } from '@testing-library/react'
import { App, queryClient } from './App'
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

    // App.tsx uses a module-level QueryClient (intentional in prod so the
    // cache survives remounts), but that means a previous test's resolved
    // ['auth','currentUser'] data sticks around for the next render and
    // suppresses the new mock's call entirely. Clear it.
    queryClient.clear()

    // Reset window.location to root — earlier tests pushState to /login,
    // /unknown-route, etc. Without this, a later test that wants to assert
    // "App at /" actually starts at whatever the previous test left behind.
    window.history.pushState({}, '', '/')

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
    it('should protect dashboard route', async () => {
      // Default mock from beforeEach: getCurrentUser rejects (unauthorized)
      render(<App />)

      // App starts at "/" (reset by beforeEach) — should redirect to /login
      expect(await screen.findByLabelText(/username/i)).toBeInTheDocument()
      expect(await screen.findByRole('button', { name: /log in/i })).toBeInTheDocument()
    })

    it('should show loading state while checking authentication', async () => {
      vi.mocked(authApi.getCurrentUser).mockImplementation(
        () => new Promise(() => {}) // Never resolves
      )

      const { container } = render(<App />)

      // LoadingSkeleton renders Skeleton elements (.animate-pulse) and a
      // pulsing Container icon — there is no "loading" text in the DOM.
      await waitFor(() => {
        expect(container.querySelector('.animate-pulse')).toBeInTheDocument()
      })
    })
  })
})
