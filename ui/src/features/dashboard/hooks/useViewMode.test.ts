/**
 * Unit tests for useViewMode hook - Phase 4b
 */

import { describe, it, expect, vi, beforeEach } from 'vitest'
import { createElement } from 'react'
import { renderHook, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { useViewMode, calculateAutoDefault } from './useViewMode'
import { apiClient } from '@/lib/api/client'
import type { ReactNode } from 'react'

// Mock the API client
vi.mock('@/lib/api/client', () => ({
  apiClient: {
    get: vi.fn(),
    post: vi.fn(),
  },
}))

describe('calculateAutoDefault', () => {
  it('should return expanded for small systems (≤10 hosts, ≤150 containers)', () => {
    expect(calculateAutoDefault(10, 150)).toBe('expanded')
    expect(calculateAutoDefault(5, 100)).toBe('expanded')
    expect(calculateAutoDefault(1, 50)).toBe('expanded')
  })

  it('should return compact when hosts exceed 10', () => {
    expect(calculateAutoDefault(11, 100)).toBe('compact')
    expect(calculateAutoDefault(15, 50)).toBe('compact')
  })

  it('should return compact when containers exceed 150', () => {
    expect(calculateAutoDefault(10, 151)).toBe('compact')
    expect(calculateAutoDefault(5, 200)).toBe('compact')
  })

  it('should return compact when both hosts and containers exceed limits', () => {
    expect(calculateAutoDefault(11, 151)).toBe('compact')
    expect(calculateAutoDefault(20, 300)).toBe('compact')
  })

  it('should handle edge cases correctly', () => {
    expect(calculateAutoDefault(0, 0)).toBe('expanded')
    expect(calculateAutoDefault(10, 0)).toBe('expanded')
    expect(calculateAutoDefault(0, 150)).toBe('expanded')
  })
})

describe('useViewMode', () => {
  let queryClient: QueryClient

  beforeEach(() => {
    queryClient = new QueryClient({
      defaultOptions: {
        queries: { retry: false },
        mutations: { retry: false },
      },
    })
    vi.clearAllMocks()
  })

  const wrapper = ({ children }: { children: ReactNode }) =>
    createElement(QueryClientProvider, { client: queryClient }, children)

  it('should fetch view mode from backend on mount', async () => {
    vi.mocked(apiClient.get).mockResolvedValue({ view_mode: 'standard' })

    const { result } = renderHook(() => useViewMode(), { wrapper })

    expect(result.current.isLoading).toBe(true)

    await waitFor(() => {
      expect(result.current.isLoading).toBe(false)
    })

    expect(apiClient.get).toHaveBeenCalledWith('/user/view-mode')
    expect(result.current.viewMode).toBe('standard')
  })

  it('should default to compact if fetch fails', async () => {
    vi.mocked(apiClient.get).mockRejectedValue(new Error('Network error'))

    const { result } = renderHook(() => useViewMode(), { wrapper })

    await waitFor(() => {
      expect(result.current.isLoading).toBe(false)
    })

    expect(result.current.viewMode).toBe('compact')
  })

  it('should save view mode to backend when setViewMode is called', async () => {
    vi.mocked(apiClient.get).mockResolvedValue({ view_mode: 'compact' })
    vi.mocked(apiClient.post).mockResolvedValue({})

    const { result } = renderHook(() => useViewMode(), { wrapper })

    await waitFor(() => {
      expect(result.current.isLoading).toBe(false)
    })

    // Change view mode
    result.current.setViewMode('expanded')

    await waitFor(() => {
      expect(apiClient.post).toHaveBeenCalledWith('/user/view-mode', { view_mode: 'expanded' })
    })
  })

  it('should optimistically update cache after successful mutation', async () => {
    vi.mocked(apiClient.get).mockResolvedValue({ view_mode: 'compact' })
    vi.mocked(apiClient.post).mockResolvedValue({})

    const { result } = renderHook(() => useViewMode(), { wrapper })

    await waitFor(() => {
      expect(result.current.viewMode).toBe('compact')
    })

    // Change view mode
    result.current.setViewMode('standard')

    await waitFor(() => {
      expect(result.current.viewMode).toBe('standard')
    })
  })

  it('should expose isUpdating state during mutation', async () => {
    vi.mocked(apiClient.get).mockResolvedValue({ view_mode: 'compact' })
    vi.mocked(apiClient.post).mockImplementation(
      () => new Promise((resolve) => setTimeout(resolve, 100))
    )

    const { result } = renderHook(() => useViewMode(), { wrapper })

    await waitFor(() => {
      expect(result.current.isLoading).toBe(false)
    })

    result.current.setViewMode('expanded')

    // Should show updating state
    await waitFor(() => {
      expect(result.current.isUpdating).toBe(true)
    })

    await waitFor(() => {
      expect(result.current.isUpdating).toBe(false)
    })
  })

  it('should handle all three view modes correctly', async () => {
    vi.mocked(apiClient.post).mockResolvedValue({})

    // Test compact - create fresh QueryClient to avoid cache
    const queryClient1 = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    const wrapper1 = ({ children }: { children: ReactNode }) =>
      createElement(QueryClientProvider, { client: queryClient1 }, children)
    vi.mocked(apiClient.get).mockResolvedValue({ view_mode: 'compact' })
    const { result: result1 } = renderHook(() => useViewMode(), { wrapper: wrapper1 })
    await waitFor(() => expect(result1.current.viewMode).toBe('compact'))

    // Test standard - create fresh QueryClient to avoid cache
    const queryClient2 = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    const wrapper2 = ({ children }: { children: ReactNode }) =>
      createElement(QueryClientProvider, { client: queryClient2 }, children)
    vi.mocked(apiClient.get).mockResolvedValue({ view_mode: 'standard' })
    const { result: result2 } = renderHook(() => useViewMode(), { wrapper: wrapper2 })
    await waitFor(() => expect(result2.current.viewMode).toBe('standard'))

    // Test expanded - create fresh QueryClient to avoid cache
    const queryClient3 = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    const wrapper3 = ({ children }: { children: ReactNode }) =>
      createElement(QueryClientProvider, { client: queryClient3 }, children)
    vi.mocked(apiClient.get).mockResolvedValue({ view_mode: 'expanded' })
    const { result: result3 } = renderHook(() => useViewMode(), { wrapper: wrapper3 })
    await waitFor(() => expect(result3.current.viewMode).toBe('expanded'))
  })
})
