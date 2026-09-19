import { describe, it, expect, beforeEach, vi, afterEach } from 'vitest'
import { renderHook, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import type { ReactNode } from 'react'
import { useStatsHistory } from './useStatsHistory'
import type { StatsHistoryResponse } from './historyTypes'
import { apiClient } from '@/lib/api/client'

// Keep in sync with MERGE_SLOT_HEADROOM in useStatsHistory.ts — it is
// deliberately not exported to keep the public surface tight.
const MERGE_SLOT_HEADROOM = 2

vi.mock('@/lib/api/client', () => ({
  apiClient: { get: vi.fn() },
}))

const mockGet = apiClient.get as unknown as ReturnType<typeof vi.fn>

function makeResponse(
  timestamps: number[],
  overrides: Partial<StatsHistoryResponse> = {},
): StatsHistoryResponse {
  return {
    tier: '1h',
    tier_seconds: 3600,
    interval_seconds: 7,
    from: timestamps[0] ?? 0,
    to: timestamps[timestamps.length - 1] ?? 0,
    server_time: timestamps[timestamps.length - 1] ?? 0,
    timestamps,
    cpu: timestamps.map((_, i) => i + 1),
    mem: timestamps.map((_, i) => 10 + i),
    net_bps: timestamps.map((_, i) => 100 + i),
    ...overrides,
  }
}

function wrapper(client: QueryClient) {
  return function Wrapper({ children }: { children: ReactNode }) {
    return <QueryClientProvider client={client}>{children}</QueryClientProvider>
  }
}

function newClient(): QueryClient {
  return new QueryClient({
    defaultOptions: { queries: { retry: false, staleTime: 0 } },
  })
}

describe('useStatsHistory', () => {
  beforeEach(() => {
    mockGet.mockReset()
  })

  afterEach(() => {
    vi.useRealTimers()
  })

  it('does not fetch when hostId is empty', () => {
    const client = newClient()
    renderHook(
      () => useStatsHistory('', undefined, '1h'),
      { wrapper: wrapper(client) },
    )
    expect(mockGet).not.toHaveBeenCalled()
  })

  it('fetches host history with range param on first call', async () => {
    mockGet.mockResolvedValueOnce(makeResponse([0, 7, 14]))
    const client = newClient()
    const { result } = renderHook(
      () => useStatsHistory('h1', undefined, '1h'),
      { wrapper: wrapper(client) },
    )
    await waitFor(() => expect(result.current.data).toBeDefined())
    expect(mockGet).toHaveBeenCalledWith(
      '/hosts/h1/stats/history',
      { params: { range: '1h' } },
    )
    expect(result.current.data?.timestamps).toEqual([0, 7, 14])
  })

  it('fetches container history with composite path on first call', async () => {
    mockGet.mockResolvedValueOnce(makeResponse([0, 7]))
    const client = newClient()
    const { result } = renderHook(
      () => useStatsHistory('h1', 'abc123abc123', '1h'),
      { wrapper: wrapper(client) },
    )
    await waitFor(() => expect(result.current.data).toBeDefined())
    expect(mockGet).toHaveBeenCalledWith(
      '/hosts/h1/containers/abc123abc123/stats/history',
      { params: { range: '1h' } },
    )
  })

  it('uses since param on subsequent polls and merges deltas', async () => {
    mockGet
      .mockResolvedValueOnce(makeResponse([0, 7, 14]))
      .mockResolvedValueOnce(makeResponse([21, 28]))
    const client = newClient()
    const { result } = renderHook(
      () => useStatsHistory('h1', undefined, '1h'),
      { wrapper: wrapper(client) },
    )
    await waitFor(() => expect(result.current.data?.timestamps).toEqual([0, 7, 14]))

    void result.current.refetch()

    await waitFor(() =>
      expect(result.current.data?.timestamps).toEqual([0, 7, 14, 21, 28])
    )

    expect(mockGet).toHaveBeenNthCalledWith(
      2,
      '/hosts/h1/stats/history',
      { params: { range: '1h', since: 14 } },
    )
  })

  it('trims oldest buckets when merged series exceeds the window slot count', async () => {
    // 1h window, interval 7s -> maxSlots ~= 3600/7 + headroom.
    const maxExpected = Math.ceil(3600 / 7) + MERGE_SLOT_HEADROOM
    const initialLen = maxExpected
    const initialTimestamps = Array.from({ length: initialLen }, (_, i) => i * 7)
    const newTimestamps = [initialTimestamps[initialTimestamps.length - 1] + 7]

    mockGet
      .mockResolvedValueOnce(makeResponse(initialTimestamps))
      .mockResolvedValueOnce(makeResponse(newTimestamps))

    const client = newClient()
    const { result } = renderHook(
      () => useStatsHistory('h1', undefined, '1h'),
      { wrapper: wrapper(client) },
    )
    await waitFor(() => expect(result.current.data?.timestamps.length).toBe(initialLen))

    void result.current.refetch()

    await waitFor(() => {
      const ts = result.current.data!.timestamps
      expect(ts[ts.length - 1]).toBe(newTimestamps[0])
      expect(ts.length).toBeLessThanOrEqual(maxExpected)
      expect(ts[0]).not.toBe(0)
    })
  })

  it('drops buckets in the poll response that are not strictly newer than cache', async () => {
    mockGet
      .mockResolvedValueOnce(makeResponse([0, 7, 14]))
      // server returns duplicate t=14 (spec bug insurance)
      .mockResolvedValueOnce(makeResponse([14, 21]))
    const client = newClient()
    const { result } = renderHook(
      () => useStatsHistory('h1', undefined, '1h'),
      { wrapper: wrapper(client) },
    )
    await waitFor(() => expect(result.current.data?.timestamps).toEqual([0, 7, 14]))
    void result.current.refetch()
    await waitFor(() =>
      expect(result.current.data?.timestamps).toEqual([0, 7, 14, 21])
    )
  })

  it('surfaces errors and leaves cached data undefined', async () => {
    mockGet.mockRejectedValueOnce(new Error('network fail'))
    const client = newClient()
    const { result } = renderHook(
      () => useStatsHistory('h1', undefined, '1h'),
      { wrapper: wrapper(client) },
    )
    await waitFor(() => expect(result.current.error).not.toBeNull())
    expect(result.current.data).toBeUndefined()
  })

  it('switches cache key on range change and does a fresh initial fetch', async () => {
    mockGet
      .mockResolvedValueOnce(makeResponse([0, 7], { tier: '1h' }))
      .mockResolvedValueOnce(makeResponse([0, 172], { tier: '24h', interval_seconds: 173 }))
    const client = newClient()
    const { result, rerender } = renderHook(
      ({ range }: { range: '1h' | '24h' }) =>
        useStatsHistory('h1', undefined, range),
      {
        wrapper: wrapper(client),
        initialProps: { range: '1h' as const },
      },
    )
    await waitFor(() => expect(result.current.data?.tier).toBe('1h'))

    rerender({ range: '24h' })
    await waitFor(() => expect(result.current.data?.tier).toBe('24h'))

    expect(mockGet).toHaveBeenNthCalledWith(
      2,
      '/hosts/h1/stats/history',
      { params: { range: '24h' } },
    )
  })
})
