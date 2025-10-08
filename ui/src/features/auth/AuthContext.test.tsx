/**
 * AuthContext Tests
 */

import { describe, it, expect, beforeEach, vi } from 'vitest'
import { renderHook, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { AuthProvider, useAuth } from './AuthContext'
import { authApi } from './api'
import type { ReactNode } from 'react'

// Mock the auth API
vi.mock('./api', () => ({
  authApi: {
    login: vi.fn(),
    logout: vi.fn(),
    getCurrentUser: vi.fn(),
  },
}))

describe('AuthContext', () => {
  let queryClient: QueryClient

  beforeEach(() => {
    // Create fresh query client for each test
    queryClient = new QueryClient({
      defaultOptions: {
        queries: { retry: false },
        mutations: { retry: false },
      },
      logger: {
        log: () => {},
        warn: () => {},
        error: () => {},
      },
    })

    vi.clearAllMocks()
  })

  const wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={queryClient}>
      <AuthProvider>{children}</AuthProvider>
    </QueryClientProvider>
  )

  describe('initial state', () => {
    it('should start with loading state when validating session', () => {
      vi.mocked(authApi.getCurrentUser).mockImplementation(
        () => new Promise(() => {}) // Never resolves
      )

      const { result } = renderHook(() => useAuth(), { wrapper })

      expect(result.current.isLoading).toBe(true)
      expect(result.current.isAuthenticated).toBe(false)
      expect(result.current.user).toBeNull()
    })

    it('should be authenticated when session is valid', async () => {
      const mockUser = { user: { id: 1, username: 'testuser' } }
      vi.mocked(authApi.getCurrentUser).mockResolvedValueOnce(mockUser)

      const { result } = renderHook(() => useAuth(), { wrapper })

      await waitFor(() => expect(result.current.isLoading).toBe(false))

      expect(result.current.isAuthenticated).toBe(true)
      expect(result.current.user).toEqual(mockUser.user)
    })

    it('should not be authenticated when session is invalid', async () => {
      vi.mocked(authApi.getCurrentUser).mockRejectedValueOnce(
        new Error('Unauthorized')
      )

      const { result } = renderHook(() => useAuth(), { wrapper })

      await waitFor(() => expect(result.current.isLoading).toBe(false))

      expect(result.current.isAuthenticated).toBe(false)
      expect(result.current.user).toBeNull()
    })
  })

  describe('login', () => {
    it('should login successfully and refetch current user', async () => {
      const mockLoginResponse = {
        user: { id: 1, username: 'testuser', is_first_login: false },
        message: 'Login successful',
      }
      const mockCurrentUser = { user: { id: 1, username: 'testuser' } }

      // Initial call returns unauthorized
      vi.mocked(authApi.getCurrentUser)
        .mockRejectedValueOnce(new Error('Unauthorized'))
        // After login, return user
        .mockResolvedValueOnce(mockCurrentUser)

      vi.mocked(authApi.login).mockResolvedValueOnce(mockLoginResponse)

      const { result } = renderHook(() => useAuth(), { wrapper })

      // Wait for initial auth check
      await waitFor(() => expect(result.current.isLoading).toBe(false))

      // Should not be authenticated initially
      expect(result.current.isAuthenticated).toBe(false)

      // Login
      await result.current.login({
        username: 'testuser',
        password: 'password',
      })

      // Wait for refetch after login
      await waitFor(() => expect(result.current.isAuthenticated).toBe(true))

      expect(authApi.login).toHaveBeenCalled()
      expect(vi.mocked(authApi.login).mock.calls[0]?.[0]).toEqual({
        username: 'testuser',
        password: 'password',
      })
      expect(result.current.user).toEqual(mockCurrentUser.user)
    })

    it('should set loading state during login', async () => {
      vi.mocked(authApi.getCurrentUser).mockRejectedValue(
        new Error('Unauthorized')
      )
      vi.mocked(authApi.login).mockImplementation(
        () => new Promise(() => {}) // Never resolves
      )

      const { result } = renderHook(() => useAuth(), { wrapper })

      await waitFor(() => expect(result.current.isLoading).toBe(false))

      // Start login (don't await)
      void result.current.login({ username: 'test', password: 'pass' })

      // Should be loading immediately
      await waitFor(() => expect(result.current.isLoading).toBe(true))
    })

    it('should throw error on login failure', async () => {
      vi.mocked(authApi.getCurrentUser).mockRejectedValue(
        new Error('Unauthorized')
      )
      vi.mocked(authApi.login).mockRejectedValueOnce(
        new Error('Invalid credentials')
      )

      const { result } = renderHook(() => useAuth(), { wrapper })

      await waitFor(() => expect(result.current.isLoading).toBe(false))

      await expect(
        result.current.login({ username: 'bad', password: 'wrong' })
      ).rejects.toThrow('Invalid credentials')
    })
  })

  describe('logout', () => {
    it('should logout and clear all queries', async () => {
      const mockUser = { user: { id: 1, username: 'testuser' } }
      vi.mocked(authApi.getCurrentUser).mockResolvedValue(mockUser)
      vi.mocked(authApi.logout).mockResolvedValueOnce()

      const { result } = renderHook(() => useAuth(), { wrapper })

      // Wait for login
      await waitFor(() => expect(result.current.isAuthenticated).toBe(true))

      // Logout
      await result.current.logout()

      expect(authApi.logout).toHaveBeenCalled()

      // Query cache should be cleared
      expect(queryClient.getQueryData(['auth', 'currentUser'])).toBeUndefined()
    })
  })

  describe('useAuth hook', () => {
    it('should throw error when used outside AuthProvider', () => {
      expect(() => {
        renderHook(() => useAuth())
      }).toThrow('useAuth must be used within AuthProvider')
    })
  })
})
