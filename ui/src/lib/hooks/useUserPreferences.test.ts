/**
 * User Preferences Hook Tests
 *
 * Tests for database-backed user preferences including:
 * - Fetching preferences
 * - Updating preferences (with optimistic updates)
 * - Resetting preferences
 * - Convenience hooks (sidebar, dashboard layout)
 */

import { describe, it, expect, beforeEach, vi } from 'vitest'
import { renderHook, waitFor, act } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import {
  useUserPreferences,
  useUpdatePreferences,
  useResetPreferences,
  useSidebarCollapsed,
  useDashboardLayout,
  type UserPreferences,
} from './useUserPreferences'
import { apiClient } from '@/lib/api/client'
import type { ReactNode } from 'react'

// Mock the API client
vi.mock('@/lib/api/client', () => ({
  apiClient: {
    get: vi.fn(),
    patch: vi.fn(),
    delete: vi.fn(),
  },
}))

describe('useUserPreferences', () => {
  let queryClient: QueryClient

  beforeEach(() => {
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
    <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
  )

  const mockPreferences: UserPreferences = {
    theme: 'dark',
    group_by: 'env',
    compact_view: false,
    collapsed_groups: [],
    filter_defaults: {},
    sidebar_collapsed: false,
    dashboard_layout_v2: null,
  }

  describe('useUserPreferences', () => {
    it('should fetch user preferences on mount', async () => {
      vi.mocked(apiClient.get).mockResolvedValueOnce(mockPreferences)

      const { result } = renderHook(() => useUserPreferences(), { wrapper })

      expect(result.current.isLoading).toBe(true)

      await waitFor(() => expect(result.current.isLoading).toBe(false))

      expect(apiClient.get).toHaveBeenCalledWith('/v2/user/preferences')
      expect(result.current.data).toEqual(mockPreferences)
    })

    it('should handle fetch errors gracefully', async () => {
      vi.mocked(apiClient.get).mockRejectedValueOnce(new Error('Network error'))

      const { result } = renderHook(() => useUserPreferences(), { wrapper })

      await waitFor(() => expect(result.current.isLoading).toBe(false))

      expect(result.current.isError).toBe(true)
      expect(result.current.data).toBeUndefined()
    })

    it('should cache preferences for 5 minutes', async () => {
      vi.mocked(apiClient.get).mockResolvedValueOnce(mockPreferences)

      const { result, rerender } = renderHook(() => useUserPreferences(), { wrapper })

      await waitFor(() => expect(result.current.isLoading).toBe(false))

      // Clear mock to ensure it's not called again
      vi.mocked(apiClient.get).mockClear()

      // Rerender - should use cache, not refetch
      rerender()

      expect(apiClient.get).not.toHaveBeenCalled()
      expect(result.current.data).toEqual(mockPreferences)
    })
  })

  describe('useUpdatePreferences', () => {
    it('should update preferences successfully', async () => {
      vi.mocked(apiClient.get).mockResolvedValueOnce(mockPreferences)
      vi.mocked(apiClient.patch).mockResolvedValueOnce({ status: 'ok' })

      const { result: prefResult } = renderHook(() => useUserPreferences(), { wrapper })
      const { result: updateResult } = renderHook(() => useUpdatePreferences(), { wrapper })

      await waitFor(() => expect(prefResult.current.isLoading).toBe(false))

      // Update sidebar state
      await act(async () => {
        updateResult.current.mutate({ sidebar_collapsed: true })
      })

      await waitFor(() => expect(updateResult.current.isSuccess).toBe(true))

      expect(apiClient.patch).toHaveBeenCalledWith('/v2/user/preferences', {
        sidebar_collapsed: true,
      })
    })

    it('should apply optimistic updates', async () => {
      vi.mocked(apiClient.get).mockResolvedValueOnce(mockPreferences)
      vi.mocked(apiClient.patch).mockImplementation(
        () => new Promise((resolve) => setTimeout(() => resolve({ status: 'ok' }), 100))
      )

      const { result: prefResult } = renderHook(() => useUserPreferences(), { wrapper })
      const { result: updateResult } = renderHook(() => useUpdatePreferences(), { wrapper })

      await waitFor(() => expect(prefResult.current.isLoading).toBe(false))

      // Apply update
      act(() => {
        updateResult.current.mutate({ sidebar_collapsed: true })
      })

      // Optimistic update should be reflected immediately
      await waitFor(() => {
        expect(prefResult.current.data?.sidebar_collapsed).toBe(true)
      })
    })

    it('should rollback on error', async () => {
      vi.mocked(apiClient.get).mockResolvedValueOnce(mockPreferences)
      vi.mocked(apiClient.patch).mockRejectedValueOnce(new Error('Server error'))

      const { result: prefResult } = renderHook(() => useUserPreferences(), { wrapper })
      const { result: updateResult } = renderHook(() => useUpdatePreferences(), { wrapper })

      await waitFor(() => expect(prefResult.current.isLoading).toBe(false))

      // Attempt update
      await act(async () => {
        updateResult.current.mutate({ sidebar_collapsed: true })
      })

      await waitFor(() => expect(updateResult.current.isError).toBe(true))

      // Should rollback to original value
      expect(prefResult.current.data?.sidebar_collapsed).toBe(false)
    })

    it('should update dashboard layout', async () => {
      const layoutUpdate = {
        widgets: [
          {
            id: 'host-stats',
            type: 'host-stats' as const,
            title: 'Host Stats',
            x: 0,
            y: 0,
            w: 2,
            h: 2,
          },
        ],
      }

      vi.mocked(apiClient.get).mockResolvedValueOnce(mockPreferences)
      vi.mocked(apiClient.patch).mockResolvedValueOnce({ status: 'ok' })

      const { result: updateResult } = renderHook(() => useUpdatePreferences(), { wrapper })

      await act(async () => {
        updateResult.current.mutate({ dashboard_layout_v2: layoutUpdate })
      })

      await waitFor(() => expect(updateResult.current.isSuccess).toBe(true))

      expect(apiClient.patch).toHaveBeenCalledWith('/v2/user/preferences', {
        dashboard_layout_v2: layoutUpdate,
      })
    })
  })

  describe('useResetPreferences', () => {
    it('should reset preferences to defaults', async () => {
      vi.mocked(apiClient.get).mockResolvedValueOnce(mockPreferences)
      vi.mocked(apiClient.delete).mockResolvedValueOnce({ status: 'ok' })

      const { result } = renderHook(() => useResetPreferences(), { wrapper })

      await act(async () => {
        result.current.mutate()
      })

      await waitFor(() => expect(result.current.isSuccess).toBe(true))

      expect(apiClient.delete).toHaveBeenCalledWith('/v2/user/preferences')
    })

    it('should invalidate queries after reset', async () => {
      vi.mocked(apiClient.get)
        .mockResolvedValueOnce(mockPreferences)
        .mockResolvedValueOnce({ ...mockPreferences, theme: 'light' })
      vi.mocked(apiClient.delete).mockResolvedValueOnce({ status: 'ok' })

      const { result: prefResult } = renderHook(() => useUserPreferences(), { wrapper })
      const { result: resetResult } = renderHook(() => useResetPreferences(), { wrapper })

      await waitFor(() => expect(prefResult.current.isLoading).toBe(false))

      // Reset
      await act(async () => {
        resetResult.current.mutate()
      })

      await waitFor(() => expect(resetResult.current.isSuccess).toBe(true))

      // Should refetch preferences
      await waitFor(() => {
        expect(apiClient.get).toHaveBeenCalledTimes(2)
      })
    })
  })

  describe('useSidebarCollapsed', () => {
    it('should return sidebar collapsed state', async () => {
      vi.mocked(apiClient.get).mockResolvedValueOnce({
        ...mockPreferences,
        sidebar_collapsed: true,
      })

      const { result } = renderHook(() => useSidebarCollapsed(), { wrapper })

      await waitFor(() => expect(result.current.isCollapsed).toBe(true))
    })

    it('should update sidebar state', async () => {
      vi.mocked(apiClient.get).mockResolvedValueOnce(mockPreferences)
      vi.mocked(apiClient.patch).mockResolvedValueOnce({ status: 'ok' })

      const { result } = renderHook(() => useSidebarCollapsed(), { wrapper })

      await waitFor(() => expect(result.current.isCollapsed).toBe(false))

      // Toggle sidebar
      await act(async () => {
        result.current.setCollapsed(true)
      })

      await waitFor(() => expect(result.current.isLoading).toBe(false))

      expect(apiClient.patch).toHaveBeenCalledWith('/v2/user/preferences', {
        sidebar_collapsed: true,
      })
    })

    it('should default to false when preferences not loaded', () => {
      vi.mocked(apiClient.get).mockImplementation(
        () => new Promise(() => {}) // Never resolves
      )

      const { result } = renderHook(() => useSidebarCollapsed(), { wrapper })

      expect(result.current.isCollapsed).toBe(false)
    })
  })

  describe('useDashboardLayout', () => {
    it('should return dashboard layout', async () => {
      const mockLayout = {
        widgets: [
          {
            id: 'host-stats',
            type: 'host-stats' as const,
            title: 'Host Stats',
            x: 0,
            y: 0,
            w: 2,
            h: 2,
          },
        ],
      }

      vi.mocked(apiClient.get).mockResolvedValueOnce({
        ...mockPreferences,
        dashboard_layout_v2: mockLayout,
      })

      const { result } = renderHook(() => useDashboardLayout(), { wrapper })

      await waitFor(() => expect(result.current.layout).toEqual(mockLayout))
    })

    it('should update dashboard layout', async () => {
      const newLayout = {
        widgets: [
          {
            id: 'container-stats',
            type: 'container-stats' as const,
            title: 'Container Stats',
            x: 2,
            y: 0,
            w: 2,
            h: 2,
          },
        ],
      }

      vi.mocked(apiClient.get).mockResolvedValueOnce(mockPreferences)
      vi.mocked(apiClient.patch).mockResolvedValueOnce({ status: 'ok' })

      const { result } = renderHook(() => useDashboardLayout(), { wrapper })

      await waitFor(() => expect(result.current.layout).toBeNull())

      // Update layout
      await act(async () => {
        result.current.setLayout(newLayout)
      })

      await waitFor(() => expect(result.current.isLoading).toBe(false))

      expect(apiClient.patch).toHaveBeenCalledWith('/v2/user/preferences', {
        dashboard_layout_v2: newLayout,
      })
    })

    it('should return null when no layout saved', async () => {
      vi.mocked(apiClient.get).mockResolvedValueOnce(mockPreferences)

      const { result } = renderHook(() => useDashboardLayout(), { wrapper })

      await waitFor(() => expect(result.current.layout).toBeNull())
    })
  })
})
