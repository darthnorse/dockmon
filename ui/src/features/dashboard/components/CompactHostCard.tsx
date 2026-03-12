import { Circle } from 'lucide-react'
import { useHostMetrics, useContainerCounts } from '@/lib/stats/StatsProvider'
import { TagChip } from '@/components/TagChip'
import type { CompactHost } from '@/features/dashboard/types'

interface CompactHostCardProps {
  host: CompactHost
  onClick?: () => void
}

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
      className="flex items-center gap-2 sm:gap-3 px-3 sm:px-4 py-2 rounded-lg border border-border bg-card hover:bg-muted transition-colors cursor-pointer group"
    >
      <Circle className={`h-2 w-2 flex-shrink-0 ${getStatusColor(host.status)}`} />

      <div className="flex-1 min-w-0 flex items-center gap-2">
        <span className="text-sm font-medium truncate">{host.name}</span>
        {host.tags && host.tags.length > 0 && (
          <div className="hidden sm:flex items-center gap-1">
            {host.tags.slice(0, 2).map((tag) => (
              <TagChip key={tag} tag={tag} size="sm" />
            ))}
            {host.tags.length > 2 && (
              <span className="text-xs text-muted-foreground">+{host.tags.length - 2}</span>
            )}
          </div>
        )}
      </div>

      <div className="flex items-center gap-1 text-xs text-muted-foreground whitespace-nowrap">
        <span className="font-mono">{containerCount}</span>
        <span className="hidden sm:inline">containers</span>
      </div>

      <div className="flex items-center gap-1 px-1.5 sm:px-2 py-1 rounded bg-amber-500/10 text-amber-600 dark:text-amber-400">
        <span className="text-xs font-mono font-semibold">{cpuPercent}%</span>
      </div>

      <div className="flex items-center gap-1 px-1.5 sm:px-2 py-1 rounded bg-blue-500/10 text-blue-600 dark:text-blue-400">
        <span className="text-xs font-mono font-semibold">{memPercent}%</span>
      </div>
    </div>
  )
}
