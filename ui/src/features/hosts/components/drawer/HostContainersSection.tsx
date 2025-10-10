/**
 * HostContainersSection Component
 *
 * Displays top 5 containers by CPU usage for a host
 */

import { Box, ArrowRight, Circle } from 'lucide-react'
import { DrawerSection } from '@/components/ui/drawer'
import { useTopContainers } from '@/lib/stats/StatsProvider'
import { Link } from 'react-router-dom'

interface HostContainersSectionProps {
  hostId: string
}

export function HostContainersSection({ hostId }: HostContainersSectionProps) {
  const topContainers = useTopContainers(hostId, 5)

  const getStatusColor = (state: string) => {
    switch (state.toLowerCase()) {
      case 'running':
        return 'text-green-500 fill-green-500'
      case 'exited':
      case 'stopped':
        return 'text-red-500 fill-red-500'
      case 'paused':
        return 'text-yellow-500 fill-yellow-500'
      case 'restarting':
        return 'text-blue-500 fill-blue-500'
      default:
        return 'text-muted-foreground fill-muted-foreground'
    }
  }

  const getStatusTextColor = (state: string) => {
    switch (state.toLowerCase()) {
      case 'running':
        return 'text-green-500'
      case 'exited':
      case 'stopped':
        return 'text-red-500'
      case 'paused':
        return 'text-yellow-500'
      case 'restarting':
        return 'text-blue-500'
      default:
        return 'text-muted-foreground'
    }
  }

  return (
    <DrawerSection title="Containers">
      {topContainers.length === 0 ? (
        <div className="text-center py-8 text-muted-foreground">
          <Box className="h-12 w-12 mx-auto mb-3 opacity-50" />
          <p className="text-sm">No containers running on this host</p>
        </div>
      ) : (
        <div className="space-y-3">
          {topContainers.map((container) => (
            <div
              key={container.id}
              className="flex items-center gap-3 p-3 rounded-lg bg-muted hover:bg-muted/80 transition-colors"
            >
              {/* Status dot */}
              <Circle className={`h-2 w-2 ${getStatusColor(container.state)}`} />

              {/* Container name */}
              <div className="flex-1 min-w-0">
                <p className="text-sm font-medium truncate">{container.name}</p>
              </div>

              {/* State */}
              <div className={`text-sm capitalize font-medium ${getStatusTextColor(container.state)}`}>
                {container.state}
              </div>
            </div>
          ))}

          {/* View All Link */}
          <Link
            to={`/containers?hostId=${hostId}`}
            className="flex items-center justify-center gap-2 p-3 rounded-lg border border-border hover:bg-muted transition-colors text-sm text-muted-foreground hover:text-foreground"
          >
            <span>View all containers on this host</span>
            <ArrowRight className="h-4 w-4" />
          </Link>
        </div>
      )}
    </DrawerSection>
  )
}
