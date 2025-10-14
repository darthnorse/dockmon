/**
 * ContainerModalLogsTab - Logs tab for container modal
 *
 * Shows logs for a single container in fullscreen modal
 */

import { LogViewer } from '@/components/logs/LogViewer'

interface ContainerModalLogsTabProps {
  hostId: string
  containerId: string
  containerName: string
}

export function ContainerModalLogsTab({ hostId, containerId, containerName }: ContainerModalLogsTabProps) {
  const containerSelection = {
    hostId,
    containerId,
    name: containerName,
  }

  return (
    <div className="h-full">
      <LogViewer
        containers={[containerSelection]}
        showContainerNames={false}
        height="calc(100vh - 300px)"
        autoRefreshDefault={true}
        showControls={true}
        compact={false}
      />
    </div>
  )
}
