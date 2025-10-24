/**
 * ContainerLogsTab - Logs tab for container drawer/modal
 *
 * Shows logs for a single container with full controls
 */

import { useContainer } from '@/lib/stats/StatsProvider'
import { LogViewer } from '@/components/logs/LogViewer'

interface ContainerLogsTabProps {
  containerId: string
}

export function ContainerLogsTab({ containerId }: ContainerLogsTabProps) {
  const container = useContainer(containerId)

  if (!container) {
    return (
      <div className="p-4 text-muted-foreground text-sm">
        Loading container details...
      </div>
    )
  }

  const containerSelection = {
    hostId: container.host_id,
    containerId: container.id,
    name: container.name,
  }

  return (
    <div className="h-full">
      <LogViewer
        containers={[containerSelection]}
        showContainerNames={false}
        height="calc(100vh - 200px)"
        autoRefreshDefault={true}
        showControls={true}
        logFontSize="xs"
      />
    </div>
  )
}
