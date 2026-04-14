import { useQuery, useQueryClient } from '@tanstack/react-query'
import { apiClient } from '@/lib/api/client'
import { VIEWS } from '@/lib/statsConfig'
import type { HistoricalRange, StatsHistoryResponse } from './historyTypes'

const POLL_INTERVAL_MS = 10_000
export const MERGE_SLOT_HEADROOM = 2  // tolerate ~2 boundary buckets of slack

// Derive the range→seconds table from the single source of truth in
// statsConfig.VIEWS. Adding a new tier requires only one edit there plus the
// matching Go cascade entry; this hook picks it up automatically.
const RANGE_SECONDS: Record<HistoricalRange, number> = Object.fromEntries(
  VIEWS.map((v) => [v.name, v.seconds]),
) as Record<HistoricalRange, number>

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
 * Build a conditional partial for an optional host-only column during merge.
 *
 * Returns `{}` when neither side has the column (so the spread is a no-op and
 * the key is absent on the merged object — required by exactOptionalPropertyTypes).
 * Returns `{ [key]: merged }` when at least one side has it, using empty arrays
 * as placeholders so a column that appears later in the cache lifetime is not
 * silently dropped.
 */
function mergeOptionalColumn<K extends 'memory_used_bytes' | 'memory_limit_bytes' | 'container_count'>(
  key: K,
  cached: (number | null)[] | undefined,
  next: (number | null)[] | undefined,
  keepIndices: number[],
): Partial<StatsHistoryResponse> {
  if (!cached && !next) return {}
  const nextPicked = next ? keepIndices.map((i) => next[i] as number | null) : []
  const merged = [...(cached ?? []), ...nextPicked]
  return { [key]: merged } as Partial<StatsHistoryResponse>
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
    // Preserve optional host-only fields when either side has them; omit
    // entirely otherwise (exactOptionalPropertyTypes disallows explicit
    // undefined). Symmetric gating means that if the seed response somehow
    // lacked a column but a later poll has it, the column is still captured
    // rather than silently dropped.
    ...mergeOptionalColumn('memory_used_bytes', cached.memory_used_bytes, next.memory_used_bytes, keepIndices),
    ...mergeOptionalColumn('memory_limit_bytes', cached.memory_limit_bytes, next.memory_limit_bytes, keepIndices),
    ...mergeOptionalColumn('container_count', cached.container_count, next.container_count, keepIndices),
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
  // TanStack Query compares queryKey structurally per render, so wrapping
  // this in useMemo adds bookkeeping without benefit. A plain array is fine.
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
