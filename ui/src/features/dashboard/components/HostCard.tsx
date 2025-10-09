/**
 * HostCard - Standard Mode Host Card Component
 * Phase 4c
 *
 * FEATURES:
 * - Host name and status indicator
 * - CPU/Memory/Network sparklines with current values
 * - Top 3 containers by CPU usage
 * - Footer badges (container count, updates, alerts)
 * - Hover effects and click navigation
 *
 * USAGE:
 * <HostCard host={hostData} />
 */

import { Circle, MoreVertical } from 'lucide-react'
import { MiniChart } from '@/lib/charts/MiniChart'
import { TagChip } from '@/components/TagChip'
import { useNavigate } from 'react-router-dom'

export interface HostCardData {
  id: string
  name: string
  url: string
  status: 'online' | 'offline' | 'error'
  tags?: string[]

  // Current stats
  stats?: {
    cpu_percent: number
    mem_percent: number
    mem_used_gb: number
    mem_total_gb: number
    net_bytes_per_sec: number
  }

  // Historical data for sparklines (last 30-40 data points)
  sparklines?: {
    cpu: number[]
    mem: number[]
    net: number[]
  }

  // Container summary
  containers?: {
    total: number
    running: number
    stopped: number
    top?: Array<{
      id: string
      name: string
      state: string
      cpu_percent: number
    }>
  }

  // Alerts & updates
  alerts?: {
    open: number
    snoozed: number
  }
  updates_available?: number
}

interface HostCardProps {
  host: HostCardData
}

/**
 * Format bytes per second to human-readable format
 */
function formatNetworkSpeed(bytesPerSec: number): string {
  if (bytesPerSec < 1024) return `${bytesPerSec.toFixed(0)} B/s`
  if (bytesPerSec < 1024 * 1024) return `${(bytesPerSec / 1024).toFixed(1)} KB/s`
  return `${(bytesPerSec / (1024 * 1024)).toFixed(1)} MB/s`
}

/**
 * Get status indicator color
 */
function getStatusColor(status: string): string {
  switch (status) {
    case 'online':
      return 'text-success fill-success'
    case 'offline':
      return 'text-muted-foreground fill-muted-foreground'
    case 'error':
      return 'text-danger fill-danger'
    default:
      return 'text-muted-foreground fill-muted-foreground'
  }
}

/**
 * Get container state color
 */
function getStateColor(state: string): string {
  switch (state.toLowerCase()) {
    case 'running':
      return 'text-success'
    case 'exited':
    case 'stopped':
      return 'text-muted-foreground'
    case 'paused':
      return 'text-warning'
    case 'restarting':
      return 'text-info'
    default:
      return 'text-muted-foreground'
  }
}

export function HostCard({ host }: HostCardProps) {
  const navigate = useNavigate()

  const hasStats = host.stats && host.sparklines
  const hasContainers = host.containers && host.containers.total > 0
  const topContainers = host.containers?.top?.slice(0, 3) || []

  return (
    <div
      className="bg-surface border border-border rounded-lg p-4 hover:shadow-lg hover:border-accent/50 transition-all cursor-pointer"
      onClick={() => navigate(`/hosts/${host.id}`)}
      role="button"
      tabIndex={0}
      onKeyDown={(e) => {
        if (e.key === 'Enter' || e.key === ' ') {
          e.preventDefault()
          navigate(`/hosts/${host.id}`)
        }
      }}
      aria-label={`Host ${host.name}, ${host.status}`}
    >
      {/* Header - Name, Status, Menu */}
      <div className="flex items-start justify-between mb-3">
        <div className="flex items-center gap-2 min-w-0 flex-1">
          <Circle className={`w-3 h-3 ${getStatusColor(host.status)}`} />
          <h3 className="text-base font-semibold text-foreground truncate">{host.name}</h3>
        </div>
        <button
          className="text-muted-foreground hover:text-foreground p-1 -mr-1"
          onClick={(e) => {
            e.stopPropagation()
            // TODO: Open actions menu (Phase 4 - Host Actions dropdown)
          }}
          aria-label="Host actions"
        >
          <MoreVertical className="w-4 h-4" />
        </button>
      </div>

      {/* Tags */}
      {host.tags && host.tags.length > 0 && (
        <div className="flex flex-wrap gap-1 mb-3">
          {host.tags.slice(0, 3).map((tag) => (
            <TagChip key={tag} tag={tag} size="sm" />
          ))}
          {host.tags.length > 3 && (
            <span className="text-xs text-muted-foreground">+{host.tags.length - 3}</span>
          )}
        </div>
      )}

      {/* Stats with Sparklines */}
      {hasStats ? (
        <div className="space-y-2 mb-3">
          {/* CPU */}
          <div className="flex items-center gap-2">
            <span className="text-xs text-muted-foreground w-8">CPU:</span>
            <div className="flex-1">
              <MiniChart
                data={host.sparklines!.cpu}
                color="cpu"
                width={120}
                height={32}
                label={`${host.name} CPU usage`}
              />
            </div>
            <span className="text-xs font-mono text-foreground w-12 text-right">
              {host.stats!.cpu_percent.toFixed(1)}%
            </span>
          </div>

          {/* Memory */}
          <div className="flex items-center gap-2">
            <span className="text-xs text-muted-foreground w-8">Mem:</span>
            <div className="flex-1">
              <MiniChart
                data={host.sparklines!.mem}
                color="memory"
                width={120}
                height={32}
                label={`${host.name} Memory usage`}
              />
            </div>
            <span className="text-xs font-mono text-foreground w-12 text-right">
              {host.stats!.mem_percent.toFixed(1)}%
            </span>
          </div>

          {/* Network */}
          <div className="flex items-center gap-2">
            <span className="text-xs text-muted-foreground w-8">Net:</span>
            <div className="flex-1">
              <MiniChart
                data={host.sparklines!.net}
                color="network"
                width={120}
                height={32}
                label={`${host.name} Network I/O`}
              />
            </div>
            <span className="text-xs font-mono text-foreground w-20 text-right">
              {formatNetworkSpeed(host.stats!.net_bytes_per_sec)}
            </span>
          </div>
        </div>
      ) : (
        <div className="text-xs text-muted-foreground mb-3">No stats available</div>
      )}

      {/* Top Containers */}
      {topContainers.length > 0 && (
        <div className="border-t border-border pt-3 mb-3">
          <div className="text-xs text-muted-foreground mb-2">Top Containers:</div>
          <div className="space-y-1">
            {topContainers.map((container) => (
              <div
                key={container.id}
                className="flex items-center justify-between text-xs"
                onClick={(e) => e.stopPropagation()}
              >
                <div className="flex items-center gap-2 min-w-0 flex-1">
                  <span className="text-foreground truncate">{container.name}</span>
                  <span className={`text-xs ${getStateColor(container.state)}`}>
                    [{container.state}]
                  </span>
                </div>
                <span className="text-muted-foreground font-mono text-xs ml-2">
                  {container.cpu_percent.toFixed(1)}%
                </span>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Footer - Badges */}
      <div className="flex items-center gap-4 text-xs border-t border-border pt-3">
        {/* Container count */}
        {hasContainers && (
          <div className="flex items-center gap-1 text-muted-foreground">
            <span>🐳</span>
            <span>
              {host.containers!.running} / {host.containers!.total}
            </span>
          </div>
        )}

        {/* Updates available */}
        {host.updates_available && host.updates_available > 0 && (
          <div className="flex items-center gap-1 text-info">
            <span>🔄</span>
            <span>{host.updates_available}</span>
          </div>
        )}

        {/* Alerts */}
        {host.alerts && (host.alerts.open > 0 || host.alerts.snoozed > 0) && (
          <div className="flex items-center gap-1 text-warning">
            <span>⚠️</span>
            <span>
              {host.alerts.open}
              {host.alerts.snoozed > 0 && ` (+${host.alerts.snoozed})`}
            </span>
          </div>
        )}
      </div>
    </div>
  )
}
