/**
 * HostCardContainer - Wrapper that connects HostCard to StatsProvider
 * Phase 4c - Stats Integration
 *
 * PURPOSE:
 * - Fetches host metrics and sparklines from StatsProvider (WebSocket data)
 * - Transforms data into HostCard format
 * - Zero HTTP requests - pure WebSocket streaming
 *
 * USAGE:
 * <HostCardContainer hostId={host.id} host={host} />
 */

import { useHostMetrics, useHostSparklines, useTopContainers } from '@/lib/stats/StatsProvider'
import { HostCard, type HostCardData } from './HostCard'

interface Host {
  id: string
  name: string
  url: string
  status: 'online' | 'offline' | 'error'
  tags?: string[]
}

interface HostCardContainerProps {
  host: Host
}

export function HostCardContainer({ host }: HostCardContainerProps) {
  // Get real-time stats from StatsProvider (WebSocket)
  const metrics = useHostMetrics(host.id)
  const sparklines = useHostSparklines(host.id)
  const topContainers = useTopContainers(host.id, 3)

  // Transform to HostCard format
  const hostCardData: HostCardData = {
    id: host.id,
    name: host.name,
    url: host.url,
    status: host.status,
    ...(host.tags && { tags: host.tags }),

    // Current stats from WebSocket
    ...(metrics && {
      stats: {
        cpu_percent: metrics.cpu_percent,
        mem_percent: metrics.mem_percent,
        mem_used_gb: metrics.mem_bytes / (1024 * 1024 * 1024), // Convert bytes to GB
        mem_total_gb: 16, // TODO: Get from host info
        net_bytes_per_sec: metrics.net_bytes_per_sec,
      },
    }),

    // Sparklines from WebSocket
    ...(sparklines && {
      sparklines: {
        cpu: sparklines.cpu,
        mem: sparklines.mem,
        net: sparklines.net,
      },
    }),

    // Top containers from WebSocket
    ...(topContainers.length > 0 && {
      containers: {
        total: topContainers.length, // TODO: Get actual total count
        running: topContainers.length, // TODO: Get actual running count
        stopped: 0, // TODO: Get actual stopped count
        top: topContainers,
      },
    }),

    // TODO: Alerts & updates (future phases)
  }

  return <HostCard host={hostCardData} />
}
