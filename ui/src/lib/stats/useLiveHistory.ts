import { useEffect, useRef, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { apiClient } from '@/lib/api/client'
import { LIVE_TIME_WINDOW } from '@/lib/statsConfig'
import { useGlobalSettings } from '@/hooks/useSettings'
import {
  useContainerStats,
  useContainerSparklines,
  useHostMetrics,
  useHostSparklines,
  useStatsMetadata,
} from './StatsProvider'
import { makeCompositeKeyFrom } from '@/lib/utils/containerKeys'
import { latestNonNull } from './columnUtils'
import type { LiveStatsResponse } from './historyTypes'

/** A single newest-tick appended to the live series from the WS broadcast. */
export interface LiveTick {
  timestamp: number
  cpu: number | null
  mem: number | null
  net: number | null
  memory_used_bytes: number | null
  memory_limit_bytes: number | null
}

/**
 * Append the newest broadcast tick to the fetched live series and trim by age
 * to the configured window. Pure so the merge/trim is unit-testable.
 *
 * - A tick whose timestamp is not strictly newer than the last point is a
 *   stale/duplicate/out-of-order broadcast and is ignored (no-op).
 * - After appending, points older than `newest - windowSeconds` are dropped,
 *   so the in-memory series stays bounded to the window (RAM scales with it).
 */
export function appendLiveTick(
  series: LiveStatsResponse,
  tick: LiveTick,
  windowSeconds: number,
): LiveStatsResponse {
  const lastTs = series.timestamps[series.timestamps.length - 1]
  if (lastTs !== undefined && tick.timestamp <= lastTs) {
    return series
  }

  const merged: LiveStatsResponse = {
    timestamps: [...series.timestamps, tick.timestamp],
    cpu: [...series.cpu, tick.cpu],
    mem: [...series.mem, tick.mem],
    net: [...series.net, tick.net],
    memory_used_bytes: [...series.memory_used_bytes, tick.memory_used_bytes],
    memory_limit_bytes: [...series.memory_limit_bytes, tick.memory_limit_bytes],
  }

  const cutoff = tick.timestamp - windowSeconds
  let drop = 0
  while (drop < merged.timestamps.length && (merged.timestamps[drop] as number) < cutoff) {
    drop++
  }
  if (drop === 0) return merged

  return {
    timestamps: merged.timestamps.slice(drop),
    cpu: merged.cpu.slice(drop),
    mem: merged.mem.slice(drop),
    net: merged.net.slice(drop),
    memory_used_bytes: merged.memory_used_bytes.slice(drop),
    memory_limit_bytes: merged.memory_limit_bytes.slice(drop),
  }
}

function liveEndpoint(hostId: string, containerId: string | undefined): string {
  return containerId
    ? `/hosts/${hostId}/containers/${containerId}/stats/live`
    : `/hosts/${hostId}/stats/live`
}

export interface UseLiveHistoryResult {
  data: LiveStatsResponse | undefined
  isLoading: boolean
  isError: boolean
  /** Window length in seconds — drives the chart's time axis. */
  windowSeconds: number
}

/**
 * On-demand live history for the detail-view Live chart.
 *
 * Fetches the configured window ONCE from the live endpoint (extended series:
 * timestamps + memory bytes), then keeps it current by appending the newest
 * point from the existing StatsProvider broadcast each WS tick -- no extra
 * polling. Returns a series bounded to the window.
 *
 * The window is the configured live_chart_window_seconds (read internally);
 * the host total memory limit is roughly constant, so appended host ticks
 * carry the last known limit forward when the broadcast doesn't supply one.
 */
export function useLiveHistory(
  hostId: string,
  containerId: string | undefined,
): UseLiveHistoryResult {
  const { data: settings } = useGlobalSettings()
  const windowSeconds = settings?.live_chart_window_seconds ?? LIVE_TIME_WINDOW
  const enabled = !!hostId
  const compositeKey = containerId ? makeCompositeKeyFrom(hostId, containerId) : null

  // One-time fetch of the window. The broadcast keeps it fresh afterwards, so
  // there is no refetch interval; the query refetches only on a fresh open.
  // windowSeconds is part of the key so changing the setting reseeds from a
  // correctly-sized backend response instead of reusing the old-window series.
  const { data: initial, isLoading, isError } = useQuery<LiveStatsResponse>({
    queryKey: ['stats-live', hostId, containerId ?? '__host__', windowSeconds],
    enabled,
    staleTime: Infinity,
    refetchOnWindowFocus: false,
    queryFn: () => apiClient.get<LiveStatsResponse>(liveEndpoint(hostId, containerId)),
  })

  // Broadcast sources for the newest tick.
  const { lastUpdate } = useStatsMetadata()
  const containerStats = useContainerStats(hostId, containerId)
  const containerSpark = useContainerSparklines(compositeKey)
  const hostMetrics = useHostMetrics(containerId ? undefined : hostId)
  const hostSpark = useHostSparklines(containerId ? undefined : hostId)

  const [series, setSeries] = useState<LiveStatsResponse | undefined>(undefined)

  // Seed (and reseed on entity change / refetch) from the one-time fetch.
  useEffect(() => {
    if (initial) setSeries(initial)
  }, [initial])

  // Append the newest broadcast tick whenever the broadcast updates.
  const lastAppendedRef = useRef<number | null>(null)
  useEffect(() => {
    if (!series || !lastUpdate) return
    const ts = Math.floor(lastUpdate.getTime() / 1000)
    if (lastAppendedRef.current === ts) return

    let tick: LiveTick
    if (containerId) {
      tick = {
        timestamp: ts,
        cpu: latestNonNull(containerSpark?.cpu) ?? containerStats?.cpu_percent ?? null,
        mem: latestNonNull(containerSpark?.mem) ?? containerStats?.memory_percent ?? null,
        net: latestNonNull(containerSpark?.net) ?? containerStats?.net_bytes_per_sec ?? null,
        memory_used_bytes: containerStats?.memory_usage ?? null,
        memory_limit_bytes: containerStats?.memory_limit ?? null,
      }
    } else {
      // Host: the broadcast carries used bytes but not the limit; carry the
      // last known limit from the series forward so byte tooltips hold.
      const lastLimit = series.memory_limit_bytes[series.memory_limit_bytes.length - 1] ?? null
      tick = {
        timestamp: ts,
        cpu: latestNonNull(hostSpark?.cpu) ?? hostMetrics?.cpu_percent ?? null,
        mem: latestNonNull(hostSpark?.mem) ?? hostMetrics?.mem_percent ?? null,
        net: latestNonNull(hostSpark?.net) ?? hostMetrics?.net_bytes_per_sec ?? null,
        memory_used_bytes: hostMetrics?.mem_bytes ?? null,
        memory_limit_bytes: lastLimit,
      }
    }

    lastAppendedRef.current = ts
    setSeries((prev) => (prev ? appendLiveTick(prev, tick, windowSeconds) : prev))
  }, [lastUpdate, series, containerId, containerStats, containerSpark, hostMetrics, hostSpark, windowSeconds])

  return { data: series, isLoading, isError, windowSeconds }
}
