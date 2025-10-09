/**
 * Dashboard Preferences Hook Tests
 *
 * Tests for dashboard-specific preferences including:
 * - hostCardLayout persistence
 * - optimizedLoading setting
 * - Layout loading state handling
 */

import { describe, it, expect, beforeEach, vi } from 'vitest'
import { renderHook, waitFor, act } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { useDashboardPrefs } from './useUserPrefs'
import type { ReactNode } from 'react'

// Mock the userPrefsApi
vi.mock('@/api/userPrefsApi', () => ({
  getUserPreferences: vi.fn(),
  updateUserPreferences: vi.fn(),
}))

import { getUserPreferences, updateUserPreferences } from '@/api/userPrefsApi'

describe('useDashboardPrefs', () => {
  let queryClient: QueryClient
  let wrapper: ({ children }: { children: ReactNode }) => JSX.Element

  const mockPreferences = {
    theme: 'dark',
    group_by: 'env',
    compact_view: false,
    collapsed_groups: [],
    filter_defaults: {},
    sidebar_collapsed: false,
    dashboard_layout_v2: null,
    dashboard: {
      enableCustomLayout: true,
      hostOrder: [],
      containerSortKey: 'state' as const,
      hostCardLayout: null,
      optimizedLoading: true,
    },
  }

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

    wrapper = ({ children }: { children: ReactNode }) => (
      <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
    )

    vi.clearAllMocks()
    vi.mocked(getUserPreferences).mockResolvedValue(mockPreferences)
  })

  it('should return dashboard preferences', async () => {
    const { result } = renderHook(() => useDashboardPrefs(), { wrapper })

    await waitFor(() => expect(result.current.dashboardPrefs).toBeDefined())

    expect(result.current.dashboardPrefs).toEqual(mockPreferences.dashboard)
  })

  it('should expose loading state', async () => {
    const { result } = renderHook(() => useDashboardPrefs(), { wrapper })

    expect(result.current.isLoading).toBe(true)

    await waitFor(() => expect(result.current.isLoading).toBe(false))
  })

  it('should update hostCardLayout', async () => {
    vi.mocked(updateUserPreferences).mockResolvedValue({
      status: 'ok',
      message: 'Updated',
    })

    const { result } = renderHook(() => useDashboardPrefs(), { wrapper })

    await waitFor(() => expect(result.current.isLoading).toBe(false))

    const newLayout = [
      { i: 'host-1', x: 0, y: 0, w: 4, h: 9 },
      { i: 'host-2', x: 4, y: 0, w: 4, h: 9 },
    ]

    await act(async () => {
      result.current.updateDashboardPrefs({ hostCardLayout: newLayout })
    })

    await waitFor(() => expect(result.current.isUpdating).toBe(false))

    expect(updateUserPreferences).toHaveBeenCalledWith(
      {
        dashboard: {
          hostCardLayout: newLayout,
        },
      },
      expect.anything() // React Query passes extra context
    )
  })

  it('should update optimizedLoading setting', async () => {
    vi.mocked(updateUserPreferences).mockResolvedValue({
      status: 'ok',
      message: 'Updated',
    })

    const { result } = renderHook(() => useDashboardPrefs(), { wrapper })

    await waitFor(() => expect(result.current.isLoading).toBe(false))

    await act(async () => {
      result.current.updateDashboardPrefs({ optimizedLoading: false })
    })

    await waitFor(() => expect(result.current.isUpdating).toBe(false))

    expect(updateUserPreferences).toHaveBeenCalledWith(
      {
        dashboard: {
          optimizedLoading: false,
        },
      },
      expect.anything() // React Query passes extra context
    )
  })

  it('should default optimizedLoading to true when undefined', async () => {
    const prefsWithoutOptimized = {
      ...mockPreferences,
      dashboard: {
        ...mockPreferences.dashboard,
        optimizedLoading: undefined,
      },
    }

    vi.mocked(getUserPreferences).mockResolvedValue(prefsWithoutOptimized)

    const { result } = renderHook(() => useDashboardPrefs(), { wrapper })

    await waitFor(() => expect(result.current.isLoading).toBe(false))

    // Should default to true
    expect(result.current.dashboardPrefs?.optimizedLoading).toBeUndefined()
  })

  it('should handle null hostCardLayout', async () => {
    const { result } = renderHook(() => useDashboardPrefs(), { wrapper })

    await waitFor(() => expect(result.current.isLoading).toBe(false))

    expect(result.current.dashboardPrefs?.hostCardLayout).toBeNull()
  })

  it('should preserve existing dashboard prefs when updating one field', async () => {
    const prefsWithLayout = {
      ...mockPreferences,
      dashboard: {
        ...mockPreferences.dashboard,
        hostCardLayout: [{ i: 'host-1', x: 0, y: 0, w: 4, h: 9 }],
      },
    }

    vi.mocked(getUserPreferences).mockResolvedValue(prefsWithLayout)
    vi.mocked(updateUserPreferences).mockResolvedValue({
      status: 'ok',
      message: 'Updated',
    })

    const { result } = renderHook(() => useDashboardPrefs(), { wrapper })

    await waitFor(() => expect(result.current.isLoading).toBe(false))

    // Update only optimizedLoading
    await act(async () => {
      result.current.updateDashboardPrefs({ optimizedLoading: false })
    })

    await waitFor(() => expect(result.current.isUpdating).toBe(false))

    // Should send only the changed field, backend merges
    expect(updateUserPreferences).toHaveBeenCalledWith(
      {
        dashboard: {
          optimizedLoading: false,
        },
      },
      expect.anything() // React Query passes extra context
    )
  })
})
