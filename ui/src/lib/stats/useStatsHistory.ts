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

function latestFilledTimestamp(data: StatsHistoryResponse): number | undefined {
  for (let i = data.timestamps.length - 1; i >= 0; i--) {
    if (data.cpu[i] != null || data.mem[i] != null || data.net_bps[i] != null) {
      return data.timestamps[i]
    }
  }
  return undefined
}

function mergeValue<T>(current: T | null | undefined, next: T | null | undefined): T | null {
  return next == null ? (current ?? null) : next
}

/**
 * Merge a `since`-poll response into cached data.
 *
 * The stats-service may include a trailing bucket for "now" before that bucket
 * has been written, represented as nulls. A later poll can return the same
 * timestamp with real values. Replace those overlap nulls instead of treating
 * timestamps as append-only, otherwise chart gaps persist until a full reload.
 */
export function mergeHistoryDelta(
  cached: StatsHistoryResponse,
  next: StatsHistoryResponse,
  range: HistoricalRange,
): StatsHistoryResponse {
  const lastCached = cached.timestamps[cached.timestamps.length - 1] ?? -Infinity
  const indexByTimestamp = new Map<number, number>()
  cached.timestamps.forEach((ts, i) => indexByTimestamp.set(ts, i))

  const merged: StatsHistoryResponse = {
    ...cached,
    to: next.to,
    server_time: next.server_time,
    // Prefer the server-fresh interval; protects trim math if stats-service
    // points_per_view is changed mid-session.
    interval_seconds: next.interval_seconds,
    timestamps: [...cached.timestamps],
    cpu: [...cached.cpu],
    mem: [...cached.mem],
    net_bps: [...cached.net_bps],
  }

  for (const key of OPTIONAL_COLUMNS) {
    const cachedCol = cached[key]
    const nextCol = next[key]
    if ((cachedCol?.length ?? 0) > 0 || (nextCol?.length ?? 0) > 0) {
      merged[key] = [...(cachedCol ?? [])]
    }
  }

  for (let i = 0; i < next.timestamps.length; i++) {
    const ts = next.timestamps[i]
    if (ts === undefined) continue

    const existingIndex = indexByTimestamp.get(ts)
    if (existingIndex !== undefined) {
      merged.cpu[existingIndex] = mergeValue(merged.cpu[existingIndex], next.cpu[i])
      merged.mem[existingIndex] = mergeValue(merged.mem[existingIndex], next.mem[i])
      merged.net_bps[existingIndex] = mergeValue(merged.net_bps[existingIndex], next.net_bps[i])

      for (const key of OPTIONAL_COLUMNS) {
        const col = merged[key]
        const nextCol = next[key]
        if (col && nextCol) {
          col[existingIndex] = mergeValue(col[existingIndex], nextCol[i])
        }
      }
      continue
    }

    if (ts <= lastCached) continue

    indexByTimestamp.set(ts, merged.timestamps.length)
    merged.timestamps.push(ts)
    merged.cpu.push(next.cpu[i] ?? null)
    merged.mem.push(next.mem[i] ?? null)
    merged.net_bps.push(next.net_bps[i] ?? null)

    for (const key of OPTIONAL_COLUMNS) {
      const col = merged[key]
      const nextCol = next[key]
      if (col && nextCol) {
        col.push(nextCol[i] ?? null)
      }
    }
  }

  const maxSlots = maxSlotsFor(range, merged.interval_seconds)
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
      const lastTs = cached ? latestFilledTimestamp(cached) : undefined
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
