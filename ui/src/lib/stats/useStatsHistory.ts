import { useMemo } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { apiClient } from '@/lib/api/client'
import type { HistoricalRange, StatsHistoryResponse } from './historyTypes'

const POLL_INTERVAL_MS = 10_000
export const MERGE_SLOT_HEADROOM = 2  // tolerate ~2 boundary buckets of slack

const RANGE_SECONDS: Record<HistoricalRange, number> = {
  '1h':  3600,
  '8h':  28800,
  '24h': 86400,
  '7d':  604800,
  '30d': 2592000,
  '60d': 5184000,
  '90d': 7776000,
}

function endpointFor(hostId: string, containerId: string | undefined): string {
  return containerId
    ? `/hosts/${hostId}/containers/${containerId}/stats/history`
    : `/hosts/${hostId}/stats/history`
}

function maxSlotsFor(range: HistoricalRange, intervalSeconds: number): number {
  const safeInterval = intervalSeconds > 0 ? intervalSeconds : 1
  return Math.ceil(RANGE_SECONDS[range] / safeInterval) + MERGE_SLOT_HEADROOM
}

/**
 * Merge a `since`-poll response into cached data.
 *
 * Contract: the server returns buckets with timestamp > `since`. This function
 * defensively drops any timestamp already present in the cache (insurance
 * against server-contract drift) and trims the leading edge of the series so
 * the length stays within the range's expected slot count.
 */
export function mergeHistoryDelta(
  cached: StatsHistoryResponse,
  next: StatsHistoryResponse,
  range: HistoricalRange,
): StatsHistoryResponse {
  const lastCached = cached.timestamps[cached.timestamps.length - 1] ?? -Infinity
  const keepIndices: number[] = []
  for (let i = 0; i < next.timestamps.length; i++) {
    const ts = next.timestamps[i]
    if (ts !== undefined && ts > lastCached) keepIndices.push(i)
  }
  if (keepIndices.length === 0) {
    // Nothing new; just refresh metadata (server_time, to).
    return { ...cached, server_time: next.server_time, to: next.to }
  }

  // Parallel-array access: keepIndices only contains valid indices from the
  // response, so arr[i] is non-undefined. Assertion avoids noUncheckedIndexedAccess friction.
  function pickColumn<T>(arr: T[] | undefined): T[] | undefined {
    if (!arr) return undefined
    return keepIndices.map((i) => arr[i] as T)
  }

  const appendedTimestamps = keepIndices.map((i) => next.timestamps[i] as number)
  const merged: StatsHistoryResponse = {
    ...cached,
    to: next.to,
    server_time: next.server_time,
    timestamps: [...cached.timestamps, ...appendedTimestamps],
    cpu:     [...cached.cpu,     ...(pickColumn(next.cpu)     ?? [])],
    mem:     [...cached.mem,     ...(pickColumn(next.mem)     ?? [])],
    net_bps: [...cached.net_bps, ...(pickColumn(next.net_bps) ?? [])],
    // Preserve optional host-only fields when present; omit entirely otherwise
    // (exactOptionalPropertyTypes disallows explicit undefined).
    ...(cached.memory_used_bytes && {
      memory_used_bytes: [
        ...cached.memory_used_bytes,
        ...(pickColumn(next.memory_used_bytes) ?? []),
      ],
    }),
    ...(cached.memory_limit_bytes && {
      memory_limit_bytes: [
        ...cached.memory_limit_bytes,
        ...(pickColumn(next.memory_limit_bytes) ?? []),
      ],
    }),
    ...(cached.container_count && {
      container_count: [
        ...cached.container_count,
        ...(pickColumn(next.container_count) ?? []),
      ],
    }),
  }

  const maxSlots = maxSlotsFor(range, cached.interval_seconds)
  if (merged.timestamps.length > maxSlots) {
    const excess = merged.timestamps.length - maxSlots
    merged.timestamps = merged.timestamps.slice(excess)
    merged.cpu = merged.cpu.slice(excess)
    merged.mem = merged.mem.slice(excess)
    merged.net_bps = merged.net_bps.slice(excess)
    if (merged.memory_used_bytes) merged.memory_used_bytes = merged.memory_used_bytes.slice(excess)
    if (merged.memory_limit_bytes) merged.memory_limit_bytes = merged.memory_limit_bytes.slice(excess)
    if (merged.container_count) merged.container_count = merged.container_count.slice(excess)
    // trim-after-append guarantees at least maxSlots >= 1 elements remain.
    merged.from = merged.timestamps[0] as number
  }

  return merged
}

/**
 * Fetches historical stats for a host or container, polls every 10s using
 * the `since` query param to get only new buckets, and merges the deltas
 * into the cached series.
 */
export function useStatsHistory(
  hostId: string,
  containerId: string | undefined,
  range: HistoricalRange,
) {
  const queryClient = useQueryClient()
  const queryKey = useMemo(
    () => ['stats-history', hostId, containerId ?? '__host__', range] as const,
    [hostId, containerId, range],
  )

  return useQuery<StatsHistoryResponse>({
    queryKey,
    enabled: !!hostId,
    refetchInterval: POLL_INTERVAL_MS,
    queryFn: async () => {
      const cached = queryClient.getQueryData<StatsHistoryResponse>(queryKey)
      const lastTs = cached?.timestamps[cached.timestamps.length - 1]
      const params: Record<string, string | number> =
        cached && lastTs !== undefined
          ? { range, since: lastTs }
          : { range }
      const next = await apiClient.get<StatsHistoryResponse>(
        endpointFor(hostId, containerId),
        { params },
      )
      if (cached) {
        return mergeHistoryDelta(cached, next, range)
      }
      return next
    },
  })
}
