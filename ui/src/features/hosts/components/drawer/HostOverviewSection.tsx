/**
 * HostOverviewSection Component
 *
 * Displays host name, status, tags, description, and uptime
 */

import { Server } from 'lucide-react'
import { DrawerSection } from '@/components/ui/drawer'
import { IpChip } from '@/components/shared/IpChip'
import type { Host } from '@/types/api'
import { formatUptime } from '@/lib/utils/formatting'

interface HostOverviewSectionProps {
  host: Host
}

export function HostOverviewSection({ host }: HostOverviewSectionProps) {
  const statusColors: Record<string, string> = {
    online: 'bg-green-500',
    offline: 'bg-red-500',
    degraded: 'bg-yellow-500',
  }

  const statusLabels: Record<string, string> = {
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
              <span className={`w-2 h-2 rounded-full ${statusColors[host.status] ?? 'bg-gray-500'}`} />
              <span className="text-sm text-muted-foreground">
                {statusLabels[host.status] ?? 'Unknown'}
              </span>
            </div>
          </div>
        </div>

        {/* URL/IP and Uptime */}
        <div className="grid grid-cols-2 gap-4">
          <div>
            {host.host_ips && host.host_ips.length > 0 ? (
              <>
                <label className="text-xs font-medium text-muted-foreground">IP Addresses</label>
                <div className="flex flex-wrap gap-1.5 mt-1">
                  {host.host_ips.map((ip) => (
                    <IpChip key={ip} ip={ip} />
                  ))}
                </div>
              </>
            ) : (
              <>
                <label className="text-xs font-medium text-muted-foreground">Endpoint</label>
                <p className="text-sm mt-1">{host.url}</p>
              </>
            )}
          </div>
          {(() => {
            const uptime = formatUptime(host.daemon_started_at)
            return uptime ? (
              <div>
                <label className="text-xs font-medium text-muted-foreground">Uptime</label>
                <p className="text-sm mt-1">{uptime}</p>
              </div>
            ) : null
          })()}
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
                <label className="text-xs font-medium text-muted-foreground">{host.is_podman ? 'Podman' : 'Docker'}</label>
                <p className="text-sm mt-1">{host.docker_version}</p>
              </div>
            )}
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
