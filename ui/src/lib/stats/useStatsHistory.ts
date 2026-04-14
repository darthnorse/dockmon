import { useQuery, useQueryClient } from '@tanstack/react-query'
import { apiClient } from '@/lib/api/client'
import { VIEWS } from '@/lib/statsConfig'
import type { HistoricalRange, StatsHistoryResponse } from './historyTypes'

const POLL_INTERVAL_MS = 10_000
// Extra slots above the exact window/interval quotient to absorb boundary
// buckets; without this we could trim a bucket the server still considers
// in-window.
const MERGE_SLOT_HEADROOM = 2

// Host-only optional columns. Tuple lets merge+trim loops share the key set.
const OPTIONAL_COLUMNS = ['memory_used_bytes', 'memory_limit_bytes', 'container_count'] as const

function endpointFor(hostId: string, containerId: string | undefined): string {
  return containerId
    ? `/hosts/${hostId}/containers/${containerId}/stats/history`
    : `/hosts/${hostId}/stats/history`
}

function maxSlotsFor(range: HistoricalRange, intervalSeconds: number): number {
  const safeInterval = intervalSeconds > 0 ? intervalSeconds : 1
  const windowSeconds = VIEWS.find((v) => v.name === range)?.seconds ?? 0
  return Math.ceil(windowSeconds / safeInterval) + MERGE_SLOT_HEADROOM
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

  // keepIndices only contains valid indices from next.timestamps, so arr[i]
  // is never undefined — the `as T` silences noUncheckedIndexedAccess.
  const pick = <T>(arr: T[]): T[] => keepIndices.map((i) => arr[i] as T)

  const merged: StatsHistoryResponse = {
    ...cached,
    to: next.to,
    server_time: next.server_time,
    timestamps: [...cached.timestamps, ...pick(next.timestamps)],
    cpu:     [...cached.cpu,     ...pick(next.cpu)],
    mem:     [...cached.mem,     ...pick(next.mem)],
    net_bps: [...cached.net_bps, ...pick(next.net_bps)],
  }

  // Symmetric gating so a column that appears later in the cache's lifetime
  // is preserved. exactOptionalPropertyTypes forbids explicit undefined, so
  // we only touch the key when at least one side has it.
  for (const key of OPTIONAL_COLUMNS) {
    const cachedCol = cached[key]
    const nextCol = next[key]
    if (cachedCol || nextCol) {
      merged[key] = [...(cachedCol ?? []), ...(nextCol ? pick(nextCol) : [])]
    }
  }

  const maxSlots = maxSlotsFor(range, cached.interval_seconds)
  if (merged.timestamps.length > maxSlots) {
    const excess = merged.timestamps.length - maxSlots
    merged.timestamps = merged.timestamps.slice(excess)
    merged.cpu = merged.cpu.slice(excess)
    merged.mem = merged.mem.slice(excess)
    merged.net_bps = merged.net_bps.slice(excess)
    for (const key of OPTIONAL_COLUMNS) {
      const col = merged[key]
      if (col) merged[key] = col.slice(excess)
    }
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
  const queryKey = ['stats-history', hostId, containerId ?? '__host__', range] as const

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
