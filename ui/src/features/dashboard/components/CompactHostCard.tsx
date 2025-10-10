/**
 * CompactHostCard Component - Phase 4d
 *
 * FEATURES:
 * - Minimal single-line host summary
 * - Status dot + name + container count + CPU/Memory badges
 * - Click to open Host Drawer
 * - Designed for high-density host lists
 *
 * USAGE:
 * ```tsx
 * <CompactHostCard
 *   host={host}
 *   onClick={() => handleHostClick(host.id)}
 * />
 * ```
 */

import { Circle } from 'lucide-react'
import { useHostMetrics, useContainerCounts } from '@/lib/stats/StatsProvider'

interface CompactHostCardProps {
  host: {
    id: string
    name: string
    url: string
    status: 'online' | 'offline' | 'error'
    tags?: string[]
  }
  onClick?: () => void
}

/**
 * Get status dot color based on host status
 */
function getStatusColor(status: string): string {
  switch (status) {
    case 'online':
      return 'fill-green-500 text-green-500'
    case 'offline':
      return 'fill-gray-500 text-gray-500'
    case 'error':
      return 'fill-red-500 text-red-500'
    default:
      return 'fill-gray-500 text-gray-500'
  }
}

export function CompactHostCard({ host, onClick }: CompactHostCardProps) {
  const hostMetrics = useHostMetrics(host.id)
  const containerCounts = useContainerCounts(host.id)

  const containerCount = `${containerCounts.running}/${containerCounts.total}`
  const cpuPercent = hostMetrics?.cpu_percent?.toFixed(0) ?? '—'
  const memPercent = hostMetrics?.mem_percent?.toFixed(0) ?? '—'

  return (
    <div
      onClick={onClick}
      className="flex items-center gap-3 px-4 py-2 rounded-lg border border-border bg-card hover:bg-muted transition-colors cursor-pointer group"
    >
      {/* Status Dot */}
      <Circle className={`h-2 w-2 ${getStatusColor(host.status)}`} />

      {/* Host Name */}
      <div className="flex-1 min-w-0">
        <span className="text-sm font-medium truncate">{host.name}</span>
      </div>

      {/* Container Count */}
      <div className="flex items-center gap-1 text-xs text-muted-foreground">
        <span className="font-mono">{containerCount}</span>
        <span>containers</span>
      </div>

      {/* CPU Badge */}
      <div className="flex items-center gap-1 px-2 py-1 rounded bg-amber-500/10 text-amber-600 dark:text-amber-400">
        <span className="text-xs font-mono font-semibold">{cpuPercent}%</span>
      </div>

      {/* Memory Badge */}
      <div className="flex items-center gap-1 px-2 py-1 rounded bg-blue-500/10 text-blue-600 dark:text-blue-400">
        <span className="text-xs font-mono font-semibold">{memPercent}%</span>
      </div>
    </div>
  )
}
