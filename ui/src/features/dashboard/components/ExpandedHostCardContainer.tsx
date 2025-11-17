/**
 * ExpandedHostCardContainer - Wrapper that connects ExpandedHostCard to StatsProvider
 * Phase 4d - Stats Integration
 *
 * PURPOSE:
 * - Fetches host metrics and all containers from StatsProvider (WebSocket data)
 * - Transforms data into ExpandedHostCard format
 * - Zero HTTP requests - pure WebSocket streaming
 *
 * USAGE:
 * <ExpandedHostCardContainer host={host} />
 */

import { useMemo } from 'react'
import { useHostMetrics, useHostSparklines, useContainerCounts } from '@/lib/stats/StatsProvider'
import { ExpandedHostCard, type ExpandedHostData } from './ExpandedHostCard'
import { useStatsContext } from '@/lib/stats/StatsProvider'
import { useIntersectionObserver } from '@/lib/hooks/useIntersectionObserver'
import { useUserPrefs } from '@/lib/hooks/useUserPreferences'
import type { Host } from '@/types/api'

interface ExpandedHostCardContainerProps {
  host: Host
  onHostClick?: (hostId: string) => void
  onViewDetails?: (hostId: string) => void
  onEditHost?: (hostId: string) => void
}

export function ExpandedHostCardContainer({ host, onHostClick, onViewDetails, onEditHost }: ExpandedHostCardContainerProps) {
  const { prefs } = useUserPrefs()
  const optimizedLoadingEnabled = prefs?.dashboard?.optimizedLoading ?? true

  // Use Intersection Observer to detect if card is visible
  const { ref: cardRef, isVisible } = useIntersectionObserver<HTMLDivElement>({
    threshold: 0,
    rootMargin: '100px', // Start loading 100px before card enters viewport
    enabled: optimizedLoadingEnabled,
  })

  // Get real-time stats from StatsProvider (WebSocket)
  const metrics = useHostMetrics(host.id)
  const sparklines = useHostSparklines(host.id)
  const containerCounts = useContainerCounts(host.id)
  const { containerStats } = useStatsContext()

  // Get all containers for this host from containerStats Map (memoized)
  const containers = useMemo(() => {
    const filtered: Array<{
      id: string
      short_id: string
      name: string
      state: string
      status: string
      cpu_percent: number | null
      memory_percent: number | null
      memory_usage: number | null
      network_rx: number | null
      network_tx: number | null
      web_ui_url?: string | null | undefined
    }> = []

    containerStats.forEach((container, compositeKey) => {
      if (compositeKey.startsWith(`${host.id}:`)) {
        filtered.push({
          id: container.id,
          short_id: container.short_id,
          name: container.name,
          state: container.state,
          status: container.status,
          cpu_percent: container.cpu_percent,
          memory_percent: container.memory_percent,
          memory_usage: container.memory_usage,
          network_rx: container.network_rx,
          network_tx: container.network_tx,
          web_ui_url: container.web_ui_url,
        })
      }
    })

    // Sort by CPU descending (most active first)
    filtered.sort((a, b) => (b.cpu_percent || 0) - (a.cpu_percent || 0))
    return filtered
  }, [containerStats, host.id])

  // Transform to ExpandedHostCard format (memoized to prevent unnecessary re-renders)
  const hostCardData = useMemo((): ExpandedHostData => {
    return {
      id: host.id,
      name: host.name,
      url: host.url,
      status: (host.status === 'degraded' ? 'error' : host.status) as 'online' | 'offline' | 'error',
      ...(host.tags && { tags: host.tags }),

      // Current stats from WebSocket
      ...(metrics && {
        stats: {
          cpu_percent: metrics.cpu_percent,
          mem_percent: metrics.mem_percent,
          mem_used_gb: metrics.mem_bytes / (1024 * 1024 * 1024), // Convert bytes to GB
          mem_total_gb: host.total_memory ? host.total_memory / (1024 * 1024 * 1024) : 0,
          net_bytes_per_sec: metrics.net_bytes_per_sec,
        },
      }),

      // Sparklines from WebSocket (only when visible for performance)
      ...(isVisible && sparklines && {
        sparklines: {
          cpu: sparklines.cpu,
          mem: sparklines.mem,
          net: sparklines.net,
        },
      }),

      // All containers from WebSocket
      ...(containerCounts.total > 0 && {
        containers: {
          total: containerCounts.total,
          running: containerCounts.running,
          stopped: containerCounts.stopped,
          items: containers,
        },
      }),

      // TODO: Alerts & updates (Phase 4e+)
    }
  }, [host, metrics, sparklines, isVisible, containerCounts, containers])

  return (
    <ExpandedHostCard
      host={hostCardData}
      cardRef={cardRef}
      {...(onHostClick && { onHostClick })}
      {...(onViewDetails && { onViewDetails })}
      {...(onEditHost && { onEditHost })}
    />
  )
}
