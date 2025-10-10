/**
 * HostOverviewSection Component
 *
 * Displays host name, status, tags, description, and uptime
 */

import { Server } from 'lucide-react'
import { TagChip } from '@/components/TagChip'
import { DrawerSection } from '@/components/ui/drawer'

interface Host {
  id: string
  name: string
  url: string
  status: 'online' | 'offline' | 'degraded'
  tags?: string[]
  description?: string
  daemon_started_at?: string | null
  os_version?: string | null
  docker_version?: string | null
}

interface HostOverviewSectionProps {
  host: Host
}

function formatUptime(daemonStartedAt?: string | null): string | null {
  if (!daemonStartedAt) return null

  try {
    const startTime = new Date(daemonStartedAt)
    const now = new Date()
    const diffMs = now.getTime() - startTime.getTime()

    const days = Math.floor(diffMs / (1000 * 60 * 60 * 24))
    const hours = Math.floor((diffMs % (1000 * 60 * 60 * 24)) / (1000 * 60 * 60))
    const minutes = Math.floor((diffMs % (1000 * 60 * 60)) / (1000 * 60))

    if (days > 0) {
      return `${days}d ${hours}h`
    } else if (hours > 0) {
      return `${hours}h ${minutes}m`
    } else {
      return `${minutes}m`
    }
  } catch {
    return null
  }
}

export function HostOverviewSection({ host }: HostOverviewSectionProps) {
  const statusColors = {
    online: 'bg-green-500',
    offline: 'bg-red-500',
    degraded: 'bg-yellow-500',
  }

  const statusLabels = {
    online: 'Online',
    offline: 'Offline',
    degraded: 'Degraded',
  }

  return (
    <DrawerSection title="Overview">
      <div className="space-y-4">
        {/* Host Name & Status */}
        <div className="flex items-center gap-3">
          <div className="p-2 rounded-lg bg-muted">
            <Server className="h-5 w-5 text-muted-foreground" />
          </div>
          <div className="flex-1 min-w-0">
            <h3 className="text-lg font-semibold truncate">{host.name}</h3>
            <div className="flex items-center gap-2 mt-1">
              <span className={`w-2 h-2 rounded-full ${statusColors[host.status]}`} />
              <span className="text-sm text-muted-foreground">
                {statusLabels[host.status]}
              </span>
            </div>
          </div>
        </div>

        {/* URL and Uptime */}
        <div className="grid grid-cols-2 gap-4">
          <div>
            <label className="text-xs font-medium text-muted-foreground">Endpoint</label>
            <p className="text-sm mt-1 font-mono text-muted-foreground">{host.url}</p>
          </div>
          {formatUptime(host.daemon_started_at) && (
            <div>
              <label className="text-xs font-medium text-muted-foreground">Uptime</label>
              <p className="text-sm mt-1">{formatUptime(host.daemon_started_at)}</p>
            </div>
          )}
        </div>

        {/* System Info */}
        {(host.os_version || host.docker_version) && (
          <div className="grid grid-cols-2 gap-4">
            {host.os_version && (
              <div>
                <label className="text-xs font-medium text-muted-foreground">OS</label>
                <p className="text-sm mt-1">{host.os_version}</p>
              </div>
            )}
            {host.docker_version && (
              <div>
                <label className="text-xs font-medium text-muted-foreground">Docker</label>
                <p className="text-sm mt-1">{host.docker_version}</p>
              </div>
            )}
          </div>
        )}

        {/* Tags */}
        {host.tags && host.tags.length > 0 && (
          <div>
            <label className="text-xs font-medium text-muted-foreground">Tags</label>
            <div className="flex flex-wrap gap-2 mt-2">
              {host.tags.map((tag) => (
                <TagChip key={tag} tag={tag} size="sm" />
              ))}
            </div>
          </div>
        )}

        {/* Description */}
        {host.description && (
          <div>
            <label className="text-xs font-medium text-muted-foreground">Description</label>
            <p className="text-sm mt-1 text-muted-foreground">{host.description}</p>
          </div>
        )}
      </div>
    </DrawerSection>
  )
}
