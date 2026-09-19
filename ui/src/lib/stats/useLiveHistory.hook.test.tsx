import { describe, it, expect, beforeEach, vi } from 'vitest'
import { renderHook, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import type { ReactNode } from 'react'
import { StatsContext, type StatsContextValue } from './StatsProvider'
import { useLiveHistory } from './useLiveHistory'
import { apiClient } from '@/lib/api/client'

vi.mock('@/lib/api/client', () => ({ apiClient: { get: vi.fn() } }))

// Controllable live-chart window setting (read by useGlobalSettings).
let mockWindow = 600
vi.mock('@/hooks/useSettings', () => ({
  useGlobalSettings: () => ({ data: { live_chart_window_seconds: mockWindow } }),
}))

const mockGet = apiClient.get as unknown as ReturnType<typeof vi.fn>

const emptyLive = {
  timestamps: [], cpu: [], mem: [], net: [],
  memory_used_bytes: [], memory_limit_bytes: [],
}

// Empty broadcast context with no lastUpdate, so the append effect is inert
// and the test isolates the one-time fetch / refetch behavior.
const emptyStats: StatsContextValue = {
  hostMetrics: new Map(),
  hostSparklines: new Map(),
  containerStats: new Map(),
  containerSparklines: new Map(),
  lastUpdate: null,
  isConnected: false,
}

function makeWrapper(client: QueryClient) {
  return function Wrapper({ children }: { children: ReactNode }) {
    return (
      <QueryClientProvider client={client}>
        <StatsContext.Provider value={emptyStats}>{children}</StatsContext.Provider>
      </QueryClientProvider>
    )
  }
}

function newClient(): QueryClient {
  return new QueryClient({ defaultOptions: { queries: { retry: false } } })
}

describe('useLiveHistory', () => {
  beforeEach(() => {
    mockGet.mockReset()
    mockGet.mockResolvedValue(emptyLive)
    mockWindow = 600
  })

  it('fetches the host live endpoint once on open', async () => {
    const { result } = renderHook(() => useLiveHistory('h1', undefined), {
      wrapper: makeWrapper(newClient()),
    })
    await waitFor(() => expect(mockGet).toHaveBeenCalledWith('/hosts/h1/stats/live'))
    expect(mockGet).toHaveBeenCalledTimes(1)
    expect(result.current.windowSeconds).toBe(600)
  })

  it('refetches the window when live_chart_window_seconds changes', async () => {
    // Regression for the query-key fix: a settings change must reseed from a
    // correctly-sized backend response, not reuse the old-window series.
    const { rerender } = renderHook(() => useLiveHistory('h1', undefined), {
      wrapper: makeWrapper(newClient()),
    })
    await waitFor(() => expect(mockGet).toHaveBeenCalledTimes(1))

    mockWindow = 1800
    rerender()

    // Without windowSeconds in the query key this never reaches 2 (same key →
    // cached, no refetch) and the test times out.
    await waitFor(() => expect(mockGet).toHaveBeenCalledTimes(2))
  })
})
